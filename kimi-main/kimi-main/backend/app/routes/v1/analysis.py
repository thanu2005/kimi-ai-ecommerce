"""Analysis endpoints for multi-agent orchestration."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage

from app.schemas import ResumeRequest, RunRequest
from app.services.agent_memory import (
    create_run_id,
    create_thread_id,
    get_action_effectiveness_overview,
    retrieve_memory_context,
    upsert_run_memory,
)
from app.services.conversation_history import (
    append_message,
    build_analysis_message,
    build_completion_message,
    ensure_thread,
    get_conversation_messages,
    mark_thread_status,
)
from app.services.observability import graph_trace_context

router = APIRouter(prefix="/api", tags=["analysis"])


def _should_include_action_effectiveness(state: dict[str, Any]) -> bool:
    """Show leaderboard only when intent extraction requests it explicitly."""
    return bool(state.get("needs_action_effectiveness", False))


def _sse(data: dict) -> str:
    """Encode a dict as a single SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


@router.post("/run/stream")
async def stream_run_analysis(req: RunRequest, request: Request) -> StreamingResponse:
    """Streaming variant of /run — emits SSE trace events for each graph node.

    Events emitted (``type`` field):
    - ``trace`` step=``supervisor``  → selected_agents, agent_goals
    - ``trace`` step=``domain_finding`` → domain, findings list
    - ``trace`` step=``retrospection`` → cross-agent reflection done
    - ``trace`` step=``synthesizer`` → synthesis complete
    - ``complete`` → thread_id, run_id, status, proposed_actions, whiteboard
    - ``error`` → message
    """
    graph = request.app.state.graph

    thread_id = req.thread_id or create_thread_id()
    run_id = create_run_id()
    config = {"configurable": {"thread_id": thread_id}}

    await ensure_thread(thread_id=thread_id, initial_query=req.query, run_id=run_id)
    await append_message(
        thread_id=thread_id,
        run_id=run_id,
        role="user",
        message_type="query",
        content=req.query,
    )
    memory_context = await retrieve_memory_context(
        req.query,
        thread_id=thread_id,
        include_cross_thread=True,
    )
    # Build prior conversation messages for context continuity
    prior_messages = []
    if req.thread_id:  # Only for existing threads (not brand new chats)
        history = await get_conversation_messages(thread_id=thread_id, limit=20)
        for m in history[:-1]:  # Exclude the message we just appended
            if m["role"] == "user":
                prior_messages.append(HumanMessage(content=m["content"]))
            elif m["role"] == "assistant":
                # Use formatted_response if available, else raw content
                text = m.get("formatted_response") or m.get("content") or ""
                if text.strip():
                    prior_messages.append(AIMessage(content=text))

    initial_state = {
        "query": req.query,
        "session_id": thread_id,
        "intent": "auto",
        "selected_agents": [],
        "whiteboard": {},
        "orchestrator_goals": "",
        "agent_goals": {},
        "memory_context": memory_context,
        "incident_memory_context": {
            "context_query": req.query,
            "include_cross_thread": True,
            "result_count": 0,
            "results": [],
        },
        "action_effectiveness_context": "",
        "messages": [*prior_messages, HumanMessage(content=req.query)],
        "proposed_actions": [],
        "pending_execution": [],
        "rejected_actions": [],
        "human_note": "",
        "iteration": 1,
        "retry_domains": [],
        "off_topic": False,
        "query_type": "REPORT",
        "requires_remediation": False,
        "needs_incident_memory": False,
        "needs_action_effectiveness": False,
        "hitl_human_reviewed": False,
    }

    async def generate():
        try:
            async for event in graph.astream_events(
                initial_state, config=config, version="v2"
            ):
                evt_type: str = event.get("event", "")
                evt_name: str = event.get("name", "")

                if evt_type != "on_chain_end":
                    continue

                output: dict = (event.get("data") or {}).get("output") or {}

                if evt_name == "supervisor":
                    yield _sse({
                        "type": "trace",
                        "step": "supervisor",
                        "selected_agents": output.get("selected_agents", []),
                        "agent_goals": output.get("agent_goals", {}),
                        "query_type": output.get("query_type", "REPORT"),
                    })

                elif evt_name == "parallel_domain_scan":
                    wb: dict = output.get("whiteboard") or {}
                    for domain, data in wb.items():
                        if not isinstance(data, dict):
                            continue
                        yield _sse({
                            "type": "trace",
                            "step": "domain_finding",
                            "domain": domain,
                            "findings": data.get("findings", []),
                        })

                elif evt_name == "collaborative_retrospection":
                    yield _sse({"type": "trace", "step": "retrospection"})

                elif evt_name == "synthesizer":
                    yield _sse({"type": "trace", "step": "synthesizer"})

                elif evt_name == "response_formatter":
                    wb_out: dict = (output.get("whiteboard") or {})
                    yield _sse({
                        "type": "trace",
                        "step": "response_formatter",
                        "formatted_response": wb_out.get("formatted_response", ""),
                    })

            # Fetch final state — use snapshot.next to reliably detect whether
            # the graph is paused at the HITL interrupt or ran to completion.
            snapshot = await graph.aget_state(config)
            state_vals: dict = snapshot.values if snapshot else {}
            proposed = state_vals.get("proposed_actions") or []
            whiteboard = state_vals.get("whiteboard") or {}
            is_paused_at_hitl = bool(snapshot and snapshot.next)
            run_status = "awaiting_approval" if is_paused_at_hitl else "completed"
            include_action_effectiveness = _should_include_action_effectiveness(state_vals)
            action_effectiveness_payload = (
                await get_action_effectiveness_overview(limit=8)
                if include_action_effectiveness
                else None
            )

            # Persist run memory
            await upsert_run_memory(
                run_id=run_id,
                thread_id=thread_id,
                query_text=req.query,
                whiteboard=whiteboard,
                proposed_actions=proposed,
                status=run_status,
                execution_result=whiteboard.get("execution_result"),
            )
            await append_message(
                thread_id=thread_id,
                run_id=run_id,
                role="assistant",
                message_type="analysis" if run_status == "awaiting_approval" else "completion",
                content=(
                    build_analysis_message(whiteboard, proposed)
                    if run_status == "awaiting_approval"
                    else build_completion_message(whiteboard, [], action_effectiveness_payload)
                ),
            )
            await mark_thread_status(thread_id=thread_id, status=run_status, run_id=run_id)

            yield _sse({
                "type": "complete",
                "thread_id": thread_id,
                "run_id": run_id,
                "status": run_status,
                "proposed_actions": proposed,
                "whiteboard": whiteboard,
                "formatted_response": whiteboard.get("formatted_response", ""),
                "action_effectiveness": action_effectiveness_payload,
                "off_topic": bool(state_vals.get("off_topic")),
                "query_type": state_vals.get("query_type", "REPORT"),
            })

        except BaseException as exc:
            detail = (
                "; ".join(str(e) for e in exc.exceptions)
                if hasattr(exc, "exceptions")
                else str(exc)
            )
            yield _sse({"type": "error", "message": detail})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def run_analysis(req: RunRequest, request: Request) -> dict[str, Any]:
    """Trigger a full multi-agent analysis run.

    The query intent is automatically extracted from the query text using
    the LLM. The system then runs only the relevant domain agents in parallel,
    followed by reflection + synthesis phases, then pauses at the HITL
    ``execute_approved_actions`` barrier.

    Returns the whiteboard contents and proposed_actions for operator review.
    """
    graph = request.app.state.graph
    langsmith_client = request.app.state.langsmith_client
    
    thread_id = req.thread_id or create_thread_id()
    run_id = create_run_id()
    config = {"configurable": {"thread_id": thread_id}}

    await ensure_thread(thread_id=thread_id, initial_query=req.query, run_id=run_id)
    await append_message(
        thread_id=thread_id,
        run_id=run_id,
        role="user",
        message_type="query",
        content=req.query,
    )

    memory_context = await retrieve_memory_context(
        req.query,
        thread_id=thread_id,
        include_cross_thread=True,
    )
    initial_state = {
        "query": req.query,
        "session_id": thread_id,
        "intent": "auto",
        "selected_agents": [],
        "whiteboard": {},
        "orchestrator_goals": "",
        "agent_goals": {},
        "memory_context": memory_context,
        "incident_memory_context": {
            "context_query": req.query,
            "include_cross_thread": True,
            "result_count": 0,
            "results": [],
        },
        "action_effectiveness_context": "",
        "messages": [HumanMessage(content=req.query)],
        "proposed_actions": [],
        "pending_execution": [],
        "rejected_actions": [],
        "human_note": "",
        "iteration": 1,
        "retry_domains": [],
        "off_topic": False,
        "query_type": "REPORT",
        "requires_remediation": False,
        "needs_incident_memory": False,
        "needs_action_effectiveness": False,
        "hitl_human_reviewed": False,
    }

    try:
        with graph_trace_context(
            client=langsmith_client,
            operation="api_run",
            thread_id=thread_id,
            run_id=run_id,
            metadata={"query": req.query[:500]},
        ):
            result = await graph.ainvoke(initial_state, config=config)
    except BaseException as exc:
        # Unwrap ExceptionGroup (from asyncio.gather / TaskGroup) for readable errors
        if hasattr(exc, "exceptions"):
            detail = "; ".join(str(e) for e in exc.exceptions)
        else:
            detail = str(exc)
        raise HTTPException(status_code=500, detail=detail)

    proposed_actions = result.get("proposed_actions", [])
    awaiting_approval = len(proposed_actions) > 0
    run_status = "awaiting_approval" if awaiting_approval else "completed"
    include_action_effectiveness = _should_include_action_effectiveness(result)
    action_effectiveness_payload = (
        await get_action_effectiveness_overview(limit=8)
        if include_action_effectiveness
        else None
    )

    await upsert_run_memory(
        run_id=run_id,
        thread_id=thread_id,
        query_text=req.query,
        whiteboard=result.get("whiteboard", {}),
        proposed_actions=proposed_actions,
        status=run_status,
        execution_result=result.get("execution_result"),
    )

    await append_message(
        thread_id=thread_id,
        run_id=run_id,
        role="assistant",
        message_type="analysis" if awaiting_approval else "completion",
        content=(
            build_analysis_message(result.get("whiteboard", {}), proposed_actions)
            if awaiting_approval
            else build_completion_message(result.get("whiteboard", {}), [], action_effectiveness_payload)
        ),
    )
    await mark_thread_status(thread_id=thread_id, status=run_status, run_id=run_id)

    response = {
        "thread_id": thread_id,
        "run_id": run_id,
        "status": run_status,
        "whiteboard": result.get("whiteboard", {}),
        "proposed_actions": proposed_actions,
        "formatted_response": (result.get("whiteboard") or {}).get("formatted_response", ""),
        "action_effectiveness": action_effectiveness_payload,
    }
    if not awaiting_approval:
        response["executed_actions"] = []
    return response


@router.post("/resume")
async def resume_analysis(req: ResumeRequest, request: Request) -> dict[str, Any]:
    """Resume a paused graph after operator approval.

    Updates the graph state with the operator-approved action list, then
    resumes execution from the ``execute_approved_actions`` node.

    Returns the final whiteboard after execution completes.
    """
    graph = request.app.state.graph
    langsmith_client = request.app.state.langsmith_client
    
    config = {"configurable": {"thread_id": req.thread_id}}
    run_id = req.run_id or create_run_id()
    has_rejections = bool(req.rejected_actions)

    approval_content = (
        f"Approved: {len(req.approved_actions)} action(s). "
        f"Rejected: {len(req.rejected_actions)} action(s)."
        + (f" Note: {req.human_note}" if req.human_note else "")
    )
    await append_message(
        thread_id=req.thread_id,
        run_id=run_id,
        role="user",
        message_type="approval",
        content=approval_content,
    )

    # Update state: approved set + rejected set + optional human note.
    # hitl_human_reviewed=True is the key that unlocks execution in
    # _route_from_hitl_gateway — it proves a human actually reviewed.
    await graph.aupdate_state(
        config,
        {
            "proposed_actions": req.approved_actions,
            "rejected_actions": req.rejected_actions,
            "human_note": req.human_note,
            "hitl_human_reviewed": True,
        },
    )

    try:
        with graph_trace_context(
            client=langsmith_client,
            operation="api_resume",
            thread_id=req.thread_id,
            run_id=run_id,
            metadata={
                "approved_count": len(req.approved_actions),
                "rejected_count": len(req.rejected_actions),
            },
        ):
            result = await graph.ainvoke(None, config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    # Use snapshot.next (same approach as the streaming endpoint) to reliably detect
    # whether the graph is still paused at a HITL interrupt or has run to completion.
    # Checking proposed_actions in state is unreliable because aupdate_state injects
    # the approved actions list before the run, so the state can be non-empty even
    # after execution finishes.
    snapshot = await graph.aget_state(config)
    is_paused_at_hitl = bool(snapshot and snapshot.next)
    state_vals: dict[str, Any] = snapshot.values if snapshot else {}
    run_status = "awaiting_approval" if is_paused_at_hitl else "completed"
    proposed_actions = result.get("proposed_actions", []) if is_paused_at_hitl else []
    pending_execution = result.get("pending_execution", [])

    await upsert_run_memory(
        run_id=run_id,
        thread_id=req.thread_id,
        query_text=(result.get("query") or "resumed-run"),
        whiteboard=result.get("whiteboard", {}),
        proposed_actions=proposed_actions or req.approved_actions,
        status=run_status,
        execution_result=result.get("whiteboard", {}).get("execution_result"),
    )

    include_action_effectiveness = _should_include_action_effectiveness(state_vals)
    action_effectiveness_payload = (
        await get_action_effectiveness_overview(limit=8)
        if include_action_effectiveness
        else None
    )

    if run_status == "completed":
        all_executed = pending_execution + req.approved_actions
        await append_message(
            thread_id=req.thread_id,
            run_id=run_id,
            role="assistant",
            message_type="completion",
            content=build_completion_message(result.get("whiteboard", {}), all_executed, action_effectiveness_payload),
        )
    else:
        await append_message(
            thread_id=req.thread_id,
            run_id=run_id,
            role="assistant",
            message_type="analysis",
            content=build_analysis_message(result.get("whiteboard", {}), proposed_actions),
        )

    await mark_thread_status(thread_id=req.thread_id, status=run_status, run_id=run_id)

    response: dict[str, Any] = {
        "thread_id": req.thread_id,
        "run_id": run_id,
        "status": run_status,
        "whiteboard": result.get("whiteboard", {}),
        "iteration": result.get("iteration", 1),
    }
    if run_status == "awaiting_approval":
        response["proposed_actions"] = proposed_actions
        response["pending_execution_count"] = len(pending_execution)
    else:
        response["executed_actions"] = pending_execution + req.approved_actions
    response["action_effectiveness"] = action_effectiveness_payload
    return response
