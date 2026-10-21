"""Long-term memory service for orchestrator threads.

Responsibilities
----------------
1. Generate stable thread and run identifiers.
2. Persist run snapshots in Postgres.
3. Embed summary + detailed history into Qdrant for semantic retrieval.
4. Retrieve relevant historical memory context for future runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any

from langchain_openai import AzureOpenAIEmbeddings
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams
from sqlalchemy import select

from app.config import settings
from app.db.models.agent_memory import AgentRunMemory
from app.db.models.agent_memory import IncidentMemory
from app.db.session import get_session

log = logging.getLogger(__name__)

VECTOR_SIZE = 1536
_KNOWN_ACTION_NAMES = {
    "restock_product_emergency",
    "update_safety_stock_trigger",
    "pause_marketing_campaign",
    "adjust_campaign_budget",
    "create_priority_dev_ticket",
}


def create_thread_id() -> str:
    """Create a thread id when frontend or API caller does not provide one."""
    return f"thread-{uuid.uuid4().hex[:12]}"


def create_run_id() -> str:
    """Create a unique run id used for memory snapshots."""
    return f"run-{uuid.uuid4().hex[:16]}"


def _stable_point_id(key: str) -> int:
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**63)


async def _ensure_memory_collection(client: AsyncQdrantClient) -> None:
    existing = await client.get_collections()
    names = [c.name for c in existing.collections]
    if settings.qdrant_agent_memory_collection not in names:
        await client.create_collection(
            collection_name=settings.qdrant_agent_memory_collection,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    embedder = AzureOpenAIEmbeddings(
        azure_endpoint=settings.dial_endpoint,
        azure_deployment=settings.dial_embedding_deployment,
        api_version=settings.dial_api_version,
        api_key=settings.dial_api_key,
        default_headers={"Api-Key": settings.dial_api_key},
    )
    return await asyncio.wait_for(embedder.aembed_documents(texts), timeout=45.0)


def _extract_domains(whiteboard: dict[str, Any]) -> list[str]:
    domains = [
        d for d in ("sales", "inventory", "marketing", "support")
        if d in whiteboard and isinstance(whiteboard.get(d), dict)
    ]
    return domains


def _infer_incident_type(query_text: str, domains: list[str]) -> str:
    q = (query_text or "").lower()
    if any(k in q for k in ("sales drop", "revenue drop", "gmv drop")):
        return "SALES_DROP"
    if any(k in q for k in ("stockout", "out of stock", "inventory")):
        return "INVENTORY_SHORTAGE"
    if any(k in q for k in ("roas", "campaign", "promotion", "discount")):
        return "MARKETING_EFFICIENCY"
    if any(k in q for k in ("ticket", "complaint", "checkout error", "refund")):
        return "SUPPORT_INCIDENT"
    if len(domains) >= 3:
        return "MULTI_DOMAIN_ANOMALY"
    return "GENERAL_OPERATIONAL_INCIDENT"


def _infer_severity(actions_executed: list[dict[str, Any]], outcome_label: str) -> str:
    if outcome_label == "WORSENED":
        return "HIGH"
    if actions_executed and outcome_label in {"IMPROVED", "STABLE"}:
        return "MEDIUM"
    if actions_executed:
        return "MEDIUM"
    return "LOW"


def _extract_executed_actions(
    execution_result: dict[str, Any] | None,
    proposed_actions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not execution_result:
        return []

    executed: list[dict[str, Any]] = []
    if isinstance(execution_result, list):
        for row in execution_result:
            if not isinstance(row, dict):
                continue
            action = str(row.get("action") or "").strip()
            if action:
                executed.append({
                    "action": action,
                    "result": row.get("result") or row.get("output"),
                    "success": not bool(row.get("error")),
                })
    elif isinstance(execution_result, dict):
        for key in ("executed_actions", "actions", "results"):
            val = execution_result.get(key)
            if isinstance(val, list):
                for row in val:
                    if not isinstance(row, dict):
                        continue
                    action = str(row.get("action") or row.get("tool") or "").strip()
                    if action:
                        executed.append({
                            "action": action,
                            "result": row.get("result") or row.get("output"),
                            "success": not bool(row.get("error")),
                        })

    if not executed and proposed_actions:
        # Fallback for completed runs where execution details were not materialized.
        for action in proposed_actions:
            name = str(action.get("action") or "").strip()
            if name:
                executed.append({"action": name, "result": None, "success": True})
    return executed


def _compute_outcome_label(
    status: str,
    execution_result: dict[str, Any] | None,
    actions_executed: list[dict[str, Any]],
) -> str:
    if status == "awaiting_approval":
        return "PENDING"
    if not actions_executed:
        return "NO_ACTION"

    failures = 0
    successes = 0
    if isinstance(execution_result, list):
        for row in execution_result:
            if isinstance(row, dict) and row.get("error"):
                failures += 1
            elif isinstance(row, dict):
                successes += 1
    elif isinstance(execution_result, dict):
        err = execution_result.get("error")
        if err:
            failures += 1
        elif execution_result:
            successes += 1

    if failures > 0 and successes == 0:
        return "WORSENED"
    if successes > 0 and failures == 0:
        return "IMPROVED"
    if successes > 0 and failures > 0:
        return "MIXED"
    return "STABLE"


def _build_incident_snapshot(
    *,
    run_id: str,
    thread_id: str,
    query_text: str,
    status: str,
    whiteboard: dict[str, Any],
    proposed_actions: list[dict[str, Any]],
    execution_result: dict[str, Any] | None,
) -> dict[str, Any]:
    domains = _extract_domains(whiteboard)
    executed_actions = _extract_executed_actions(execution_result, proposed_actions)
    outcome_label = _compute_outcome_label(status, execution_result, executed_actions)
    incident_type = _infer_incident_type(query_text, domains)

    findings_chunks: list[str] = []
    for d in domains:
        findings = (whiteboard.get(d) or {}).get("findings", [])
        if findings:
            findings_chunks.append(f"{d}: {' | '.join(str(f) for f in findings[:3])}")
    symptoms_text = "\n".join(findings_chunks).strip() or "No explicit findings captured."

    root_cause_text = str(whiteboard.get("final_report") or "").strip()
    if len(root_cause_text) > 1200:
        root_cause_text = root_cause_text[:1200]

    evidence_refs = [
        {
            "run_id": run_id,
            "thread_id": thread_id,
            "status": status,
        }
    ]

    outcome_metrics = {
        "execution_count": len(executed_actions),
        "successful_execution_count": sum(1 for a in executed_actions if a.get("success", True)),
        "failure_execution_count": sum(1 for a in executed_actions if not a.get("success", True)),
        "domain_count": len(domains),
    }

    severity = _infer_severity(executed_actions, outcome_label)
    incident_id = f"inc-{run_id.replace('run-', '')}"
    return {
        "incident_id": incident_id,
        "run_id": run_id,
        "thread_id": thread_id,
        "query_text": query_text,
        "incident_type": incident_type,
        "severity": severity,
        "time_window": None,
        "domains_json": domains,
        "symptoms_text": symptoms_text,
        "root_cause_text": root_cause_text,
        "actions_executed_json": executed_actions,
        "outcome_metrics_json": outcome_metrics,
        "outcome_label": outcome_label,
        "evidence_refs_json": evidence_refs,
    }


def _incident_to_text(incident: dict[str, Any]) -> str:
    return (
        f"incident_id={incident['incident_id']}\n"
        f"incident_type={incident['incident_type']}\n"
        f"severity={incident['severity']}\n"
        f"outcome_label={incident['outcome_label']}\n"
        f"query={incident['query_text']}\n"
        f"domains={', '.join(incident.get('domains_json', []))}\n"
        f"symptoms={incident['symptoms_text']}\n"
        f"root_cause={incident['root_cause_text']}\n"
        f"actions={json.dumps(incident.get('actions_executed_json', []), default=str)}"
    )


async def upsert_run_memory(
    *,
    run_id: str,
    thread_id: str,
    query_text: str,
    whiteboard: dict[str, Any],
    proposed_actions: list[dict[str, Any]],
    status: str,
    execution_result: dict[str, Any] | None = None,
) -> None:
    """Persist run memory in Postgres and vectorize summary + detailed forms."""
    summary = str(whiteboard.get("final_report") or "").strip()
    if not summary:
        summary = (
            f"Query: {query_text}\n"
            f"Status: {status}\n"
            f"Proposed actions: {len(proposed_actions)}"
        )

    details_obj = {
        "query": query_text,
        "status": status,
        "whiteboard": whiteboard,
        "proposed_actions": proposed_actions,
        "execution_result": execution_result or {},
    }
    details = json.dumps(details_obj, default=str)
    incident = _build_incident_snapshot(
        run_id=run_id,
        thread_id=thread_id,
        query_text=query_text,
        status=status,
        whiteboard=whiteboard,
        proposed_actions=proposed_actions,
        execution_result=execution_result,
    )
    incident_text = _incident_to_text(incident)
    now = datetime.utcnow()

    # Upsert in Postgres by run_id
    async with get_session() as session:
        result = await session.execute(
            select(AgentRunMemory).where(AgentRunMemory.run_id == run_id)
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = AgentRunMemory(
                run_id=run_id,
                thread_id=thread_id,
                query_text=query_text,
                status=status,
                summary_text=summary,
                detailed_text=details,
                whiteboard_json=whiteboard,
                proposed_actions_json=proposed_actions,
                execution_result_json=execution_result,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.thread_id = thread_id
            row.query_text = query_text
            row.status = status
            row.summary_text = summary
            row.detailed_text = details
            row.whiteboard_json = whiteboard
            row.proposed_actions_json = proposed_actions
            row.execution_result_json = execution_result
            row.updated_at = now

        incident_result = await session.execute(
            select(IncidentMemory).where(IncidentMemory.run_id == run_id)
        )
        incident_row = incident_result.scalar_one_or_none()
        if incident_row is None:
            incident_row = IncidentMemory(
                incident_id=incident["incident_id"],
                run_id=run_id,
                thread_id=thread_id,
                query_text=query_text,
                incident_type=incident["incident_type"],
                severity=incident["severity"],
                time_window=incident["time_window"],
                domains_json=incident["domains_json"],
                symptoms_text=incident["symptoms_text"],
                root_cause_text=incident["root_cause_text"],
                actions_executed_json=incident["actions_executed_json"],
                outcome_metrics_json=incident["outcome_metrics_json"],
                outcome_label=incident["outcome_label"],
                evidence_refs_json=incident["evidence_refs_json"],
                created_at=now,
                updated_at=now,
            )
            session.add(incident_row)
        else:
            incident_row.thread_id = thread_id
            incident_row.query_text = query_text
            incident_row.incident_type = incident["incident_type"]
            incident_row.severity = incident["severity"]
            incident_row.time_window = incident["time_window"]
            incident_row.domains_json = incident["domains_json"]
            incident_row.symptoms_text = incident["symptoms_text"]
            incident_row.root_cause_text = incident["root_cause_text"]
            incident_row.actions_executed_json = incident["actions_executed_json"]
            incident_row.outcome_metrics_json = incident["outcome_metrics_json"]
            incident_row.outcome_label = incident["outcome_label"]
            incident_row.evidence_refs_json = incident["evidence_refs_json"]
            incident_row.updated_at = now

    # Vectorize summary + details for retrieval
    try:
        vectors = await _embed_texts([summary, details, incident_text])
        client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        await _ensure_memory_collection(client)

        created_ts = int(time.time())
        points = [
            PointStruct(
                id=_stable_point_id(f"{run_id}:summary"),
                vector=vectors[0],
                payload={
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "memory_type": "summary",
                    "text": summary,
                    "status": status,
                    "query_text": query_text,
                    "created_at_timestamp": created_ts,
                },
            ),
            PointStruct(
                id=_stable_point_id(f"{run_id}:details"),
                vector=vectors[1],
                payload={
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "memory_type": "details",
                    "text": details,
                    "status": status,
                    "query_text": query_text,
                    "created_at_timestamp": created_ts,
                },
            ),
            PointStruct(
                id=_stable_point_id(f"{run_id}:incident"),
                vector=vectors[2],
                payload={
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "memory_type": "incident",
                    "text": incident_text,
                    "incident_id": incident["incident_id"],
                    "incident_type": incident["incident_type"],
                    "severity": incident["severity"],
                    "outcome_label": incident["outcome_label"],
                    "domains": incident["domains_json"],
                    "created_at_timestamp": created_ts,
                },
            ),
        ]

        await client.upsert(
            collection_name=settings.qdrant_agent_memory_collection,
            points=points,
        )
        await client.close()

        async with get_session() as session:
            result = await session.execute(
                select(AgentRunMemory).where(AgentRunMemory.run_id == run_id)
            )
            row = result.scalar_one_or_none()
            if row is not None:
                row.vectorized_at = datetime.utcnow()
                row.updated_at = datetime.utcnow()

            inc_result = await session.execute(
                select(IncidentMemory).where(IncidentMemory.run_id == run_id)
            )
            inc = inc_result.scalar_one_or_none()
            if inc is not None:
                inc.vectorized_at = datetime.utcnow()
                inc.updated_at = datetime.utcnow()

    except Exception as exc:
        # Memory persistence in Postgres is critical; vectorization is best-effort.
        log.warning("Run memory vectorization failed for %s: %s", run_id, exc)


async def retrieve_memory_context(
    query_text: str,
    thread_id: str,
    limit: int = 4,
    include_cross_thread: bool = True,
) -> str:
    """Return semantically relevant historical memory snippets.

    When ``include_cross_thread`` is True, retrieval runs across all threads
    in the incident memory store and tags each hit as THREAD or GLOBAL.
    """
    try:
        embedder = AzureOpenAIEmbeddings(
            azure_endpoint=settings.dial_endpoint,
            azure_deployment=settings.dial_embedding_deployment,
            api_version=settings.dial_api_version,
            api_key=settings.dial_api_key,
            default_headers={"Api-Key": settings.dial_api_key},
        )
        query_vector = await asyncio.wait_for(embedder.aembed_query(query_text), timeout=30.0)

        client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        await _ensure_memory_collection(client)

        must_conditions = [FieldCondition(key="memory_type", match=MatchValue(value="summary"))]
        if not include_cross_thread:
            must_conditions.append(FieldCondition(key="thread_id", match=MatchValue(value=thread_id)))
        qfilter = Filter(must=must_conditions)

        hits = await asyncio.wait_for(
            client.search(
                collection_name=settings.qdrant_agent_memory_collection,
                query_vector=query_vector,
                query_filter=qfilter,
                limit=limit,
                with_payload=True,
            ),
            timeout=8.0,
        )
        await client.close()

        if not hits:
            return ""

        lines: list[str] = []
        for idx, hit in enumerate(hits, start=1):
            payload = hit.payload or {}
            text = str(payload.get("text", "")).strip()
            if not text:
                continue
            tag = "THREAD" if payload.get("thread_id") == thread_id else "GLOBAL"
            lines.append(
                f"[{idx}] {tag} score={hit.score:.3f} run_id={payload.get('run_id', '')}: {text}"
            )

        return "\n".join(lines)
    except Exception as exc:
        log.warning("Memory retrieval failed for thread %s: %s", thread_id, exc)
        return ""


async def retrieve_incident_memories(
    *,
    context_query: str,
    thread_id: str | None = None,
    limit: int = 5,
    include_cross_thread: bool = True,
    incident_type: str | None = None,
) -> dict[str, Any]:
    """Search incident memory using a context query and Qdrant similarity."""
    try:
        embedder = AzureOpenAIEmbeddings(
            azure_endpoint=settings.dial_endpoint,
            azure_deployment=settings.dial_embedding_deployment,
            api_version=settings.dial_api_version,
            api_key=settings.dial_api_key,
            default_headers={"Api-Key": settings.dial_api_key},
        )
        vector = await asyncio.wait_for(embedder.aembed_query(context_query), timeout=30.0)

        client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        await _ensure_memory_collection(client)

        must_conditions = [FieldCondition(key="memory_type", match=MatchValue(value="incident"))]
        if thread_id and not include_cross_thread:
            must_conditions.append(FieldCondition(key="thread_id", match=MatchValue(value=thread_id)))
        if incident_type:
            must_conditions.append(FieldCondition(key="incident_type", match=MatchValue(value=incident_type)))

        hits = await asyncio.wait_for(
            client.search(
                collection_name=settings.qdrant_agent_memory_collection,
                query_vector=vector,
                query_filter=Filter(must=must_conditions),
                limit=limit,
                with_payload=True,
            ),
            timeout=10.0,
        )
        await client.close()

        results: list[dict[str, Any]] = []
        for i, hit in enumerate(hits, start=1):
            p = hit.payload or {}
            results.append(
                {
                    "rank": i,
                    "score": round(hit.score, 4),
                    "scope": (
                        "thread"
                        if thread_id and p.get("thread_id") == thread_id
                        else "cross_thread"
                    ),
                    "incident_id": p.get("incident_id"),
                    "run_id": p.get("run_id"),
                    "thread_id": p.get("thread_id"),
                    "incident_type": p.get("incident_type"),
                    "severity": p.get("severity"),
                    "outcome_label": p.get("outcome_label"),
                    "domains": p.get("domains", []),
                    "text": p.get("text", ""),
                }
            )

        return {
            "context_query": context_query,
            "include_cross_thread": include_cross_thread,
            "result_count": len(results),
            "results": results,
        }
    except Exception as exc:
        log.warning("Incident retrieval failed: %s", exc)
        return {
            "context_query": context_query,
            "include_cross_thread": include_cross_thread,
            "result_count": 0,
            "results": [],
            "error": str(exc),
        }


def _normalize_action_name(action: dict[str, Any]) -> str:
    raw = str(
        action.get("action")
        or action.get("tool")
        or action.get("action_type")
        or action.get("name")
        or ""
    ).strip()
    if raw in _KNOWN_ACTION_NAMES:
        return raw
    return raw


async def get_action_effectiveness_overview(
    *,
    incident_type: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Aggregate historical action effectiveness across incident memories."""
    async with get_session() as session:
        result = await session.execute(select(IncidentMemory))
        rows = result.scalars().all()

    stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        if incident_type and row.incident_type != incident_type:
            continue
        actions = row.actions_executed_json or []
        for action in actions:
            if not isinstance(action, dict):
                continue
            name = _normalize_action_name(action)
            if not name:
                continue
            s = stats.setdefault(
                name,
                {
                    "action": name,
                    "count": 0,
                    "improved": 0,
                    "mixed": 0,
                    "worsened": 0,
                    "stable": 0,
                    "pending": 0,
                    "no_action": 0,
                    "success_count": 0,
                },
            )
            s["count"] += 1
            label = (row.outcome_label or "UNKNOWN").upper()
            if label == "IMPROVED":
                s["improved"] += 1
            elif label == "MIXED":
                s["mixed"] += 1
            elif label == "WORSENED":
                s["worsened"] += 1
            elif label == "STABLE":
                s["stable"] += 1
            elif label == "PENDING":
                s["pending"] += 1
            elif label == "NO_ACTION":
                s["no_action"] += 1
            if label in {"IMPROVED", "STABLE"}:
                s["success_count"] += 1

    ranked = []
    for _, s in stats.items():
        success_rate = round((s["success_count"] / s["count"]) * 100, 2) if s["count"] else 0.0
        confidence = "HIGH" if s["count"] >= 6 else "MEDIUM" if s["count"] >= 3 else "LOW"
        ranked.append(
            {
                "action": s["action"],
                "count": s["count"],
                "success_count": s["success_count"],
                "success_rate": success_rate,
                "outcomes": {
                    "improved": s["improved"],
                    "stable": s["stable"],
                    "mixed": s["mixed"],
                    "worsened": s["worsened"],
                    "pending": s["pending"],
                    "no_action": s["no_action"],
                },
                "confidence": confidence,
            }
        )

    ranked.sort(key=lambda x: (x["success_rate"], x["count"]), reverse=True)
    top = ranked[: max(1, limit)]

    return {
        "incident_type_filter": incident_type,
        "total_distinct_actions": len(ranked),
        "top_actions": top,
    }


def build_action_effectiveness_context(effectiveness: dict[str, Any]) -> str:
    """Render compact textual context for agent prompts and synthesis."""
    top = effectiveness.get("top_actions") or []
    if not top:
        return "No historical action effectiveness evidence available yet."
    lines = ["Historical action effectiveness (cross-thread):"]
    for i, row in enumerate(top[:5], start=1):
        lines.append(
            f"{i}. {row['action']} — success_rate={row['success_rate']}% "
            f"(n={row['count']}, confidence={row['confidence']})"
        )
    return "\n".join(lines)
