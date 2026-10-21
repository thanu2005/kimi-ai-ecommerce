"""Support-domain MCP tools.

All six tools in this module interact with the ``customer_support_tickets``
table, the ``order_items`` table (for fulfillment delay analysis), and the
Qdrant vector database (for semantic historical incident retrieval).

Read tools (safe to call during any agent analysis cycle):
    - get_support_ticket_metrics       : Daily ticket volume, resolution times, category breakdown.
    - query_historical_incidents_qdrant: Semantic vector search over historical resolved tickets.
    - search_ticket_sentiments         : Keyword-based ticket search with sentiment scores.
    - get_product_return_reasons       : Resolution-type breakdown for a specific product.
    - get_fulfillment_delay_analysis   : Orders where actual_delivery > estimated_delivery.

Write / action tools (must only be called from the HITL execute_approved_actions
node after explicit operator approval):
    - create_priority_dev_ticket : Logs a bug/incident into the engineering queue.

Registration
------------
Called once during server startup via::

    from mcp_server.tools.support import register
    register(mcp)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import case
from sqlalchemy import func
from sqlalchemy import select

from app.config import settings
from app.db.models.sales import OrderItem
from app.db.models.support import CustomerSupportTicket
from app.db.models.support import ResolutionType
from app.db.models.support import TicketCategory
from app.db.models.support import TicketStatus
from app.db.session import get_session

log = logging.getLogger(__name__)


def register(mcp) -> None:
    """Register all support-domain tools onto the provided FastMCP instance.

    Parameters
    ----------
    mcp : FastMCP
        The shared FastMCP application instance created in ``mcp_server.server``.
    """

    # ----------------------------------------------------------------------- #
    #  Helpers                                                                 #
    # ----------------------------------------------------------------------- #

    def _day_window(d: date_type) -> tuple[datetime, datetime]:
        return (
            datetime(d.year, d.month, d.day, 0, 0, 0),
            datetime(d.year, d.month, d.day, 23, 59, 59),
        )

    def _enum_val(v) -> str:
        return v.value if hasattr(v, "value") else str(v)

    # ----------------------------------------------------------------------- #
    #  READ TOOLS                                                              #
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    async def get_support_ticket_metrics(date: str) -> dict:
        """Return daily support ticket volume, category distribution, and resolution time metrics.

        Aggregates ``customer_support_tickets`` for the specified calendar day,
        providing the Support Agent with a customer health radar across four
        dimensions:

        1. **Volume summary** — total tickets opened, broken down by status
           (OPEN, IN_PROGRESS, RESOLVED, ESCALATED).
        2. **Category distribution** — ticket counts and percentage share for
           each ``ticket_category``: Checkout_Error, Shipping_Delay,
           Product_Defect, Refund_Request.
        3. **Priority distribution** — ticket counts by urgency tier
           (LOW, MEDIUM, HIGH, CRITICAL).
        4. **Resolution time** — average hours between ``created_at`` and
           ``resolved_at`` for tickets that were resolved on this day.  NULL
           ``resolved_at`` values are excluded from the calculation.

        A category spike — e.g., Checkout_Error tickets tripling in one hour —
        is the Support Agent's earliest signal of a systemic platform problem
        that the Sales Agent's payment gateway data can confirm.  CRITICAL
        priority spikes trigger the Support Agent to immediately search
        historical incidents via ``query_historical_incidents_qdrant`` for
        precedent-based resolution options.

        Parameters
        ----------
        date : str — Calendar day in ``YYYY-MM-DD`` format.

        Returns
        -------
        dict
            Keys:
            - date                   : str
            - total_tickets          : int
            - status_breakdown       : dict — {status_name: count}
            - category_breakdown     : list[dict] — each entry has:
                  category, count, share_pct, avg_sentiment.
            - priority_breakdown     : dict — {priority_name: count}
            - avg_resolution_hours   : float | None — mean resolution time for
                                       tickets resolved on this day.
            - unresolved_count       : int — OPEN + IN_PROGRESS + ESCALATED.

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [SUPPORT] get_support_ticket_metrics called | date={date}")
        try:
            target = date_type.fromisoformat(date)
        except ValueError:
            return {"error": f"Invalid date format '{date}'. Expected YYYY-MM-DD."}

        day_start, day_end = _day_window(target)

        async with get_session() as session:
            # All tickets opened on this day
            tickets_result = await session.execute(
                select(CustomerSupportTicket).where(
                    CustomerSupportTicket.created_at >= day_start,
                    CustomerSupportTicket.created_at <= day_end,
                )
            )
            tickets = tickets_result.scalars().all()

        if not tickets:
            return {
                "date": date,
                "total_tickets": 0,
                "status_breakdown": {},
                "category_breakdown": [],
                "priority_breakdown": {},
                "avg_resolution_hours": None,
                "unresolved_count": 0,
            }

        # Status breakdown
        status_counts: dict[str, int] = {}
        for t in tickets:
            s = _enum_val(t.ticket_status)
            status_counts[s] = status_counts.get(s, 0) + 1

        # Priority breakdown
        priority_counts: dict[str, int] = {}
        for t in tickets:
            p = _enum_val(t.priority)
            priority_counts[p] = priority_counts.get(p, 0) + 1

        # Category distribution with avg sentiment
        cat_buckets: dict[str, list] = {}
        for t in tickets:
            c = _enum_val(t.ticket_category)
            cat_buckets.setdefault(c, []).append(float(t.sentiment_score))

        total = len(tickets)
        category_breakdown = [
            {
                "category": cat,
                "count": len(scores),
                "share_pct": round((len(scores) / total) * 100, 2),
                "avg_sentiment": round(sum(scores) / len(scores), 3),
            }
            for cat, scores in sorted(cat_buckets.items(), key=lambda x: -len(x[1]))
        ]

        # Resolution time (resolved tickets only)
        resolution_hours = [
            (t.resolved_at - t.created_at).total_seconds() / 3600
            for t in tickets
            if t.resolved_at is not None and _enum_val(t.ticket_status) == "RESOLVED"
        ]
        avg_resolution = (
            round(sum(resolution_hours) / len(resolution_hours), 2)
            if resolution_hours
            else None
        )

        unresolved = sum(
            1 for t in tickets
            if _enum_val(t.ticket_status) in ("OPEN", "IN_PROGRESS", "ESCALATED")
        )

        return {
            "date": date,
            "total_tickets": total,
            "status_breakdown": status_counts,
            "category_breakdown": category_breakdown,
            "priority_breakdown": priority_counts,
            "avg_resolution_hours": avg_resolution,
            "unresolved_count": unresolved,
        }

    @mcp.tool()
    async def query_historical_incidents_qdrant(
        query_text: str,
        filter_metadata: dict = None,
    ) -> dict:
        """Perform a semantic vector similarity search over historical resolved support tickets.

        Connects to the Qdrant vector database (collection:
        ``support_ticket_embeddings``) and returns the top-N most semantically
        similar historical tickets to the provided query text.  Each result
        includes the matched ticket's stored payload metadata and a cosine
        similarity score.

        This tool satisfies the **Memory/Learning requirement** of the
        multi-agent system.  Before proposing a resolution action, the Support
        Agent must call this tool to determine whether a similar past incident
        exists and how it was resolved by a human operator.  Learning from
        historical precedent prevents the agent from proposing novel untested
        actions when a proven playbook already exists.

        Vector payload fields returned per result
        ------------------------------------------
        The Qdrant payload for each stored vector contains:

        - ticket_id              : str — links back to ``customer_support_tickets``.
        - product_id             : str
        - ticket_category        : str
        - sentiment_score        : float
        - resolution_type        : str — the action that resolved the incident.
        - created_at_timestamp   : int — Unix epoch of the original ticket.

        Optional metadata filtering
        ---------------------------
        ``filter_metadata`` accepts a flat dict of payload key/value pairs to
        pre-filter results before scoring.  Example::

            {"ticket_category": "Checkout_Error", "resolution_type": "COUPON_FIXED"}

        Only exact-match equality filters are supported.  Leave as ``None`` to
        perform an unfiltered semantic search across all resolved tickets.

        Parameters
        ----------
        query_text      : str  — Natural language description of the incident
                          being investigated (e.g., ``"customers unable to apply
                          promo code at checkout for yoga mat"``).
        filter_metadata : dict — Optional payload filter dict (see above).
                          Defaults to ``None`` (no filter).

        Returns
        -------
        dict
            Keys:
            - query_text       : str
            - filters_applied  : dict | None
            - result_count     : int
            - results          : list[dict] — each entry has:
                  rank, ticket_id, score (0–1), product_id,
                  ticket_category, sentiment_score, resolution_type,
                  created_at_timestamp.

            Returns ``{"error": "..."}`` if Qdrant is unreachable or the
            collection does not exist.
        """
        log.info(f"📞 [SUPPORT] query_historical_incidents_qdrant called | query_text={query_text[:50]}, filter_metadata={filter_metadata}")
        from qdrant_client import AsyncQdrantClient
        from qdrant_client.http.models import Filter, FieldCondition, MatchValue

        try:
            client = AsyncQdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port,
            )

            # Build optional payload filter
            qdrant_filter = None
            if filter_metadata:
                conditions = [
                    FieldCondition(key=k, match=MatchValue(value=v))
                    for k, v in filter_metadata.items()
                ]
                qdrant_filter = Filter(must=conditions)

            # Generate embedding for query_text using the configured OpenAI model
            import asyncio
            from langchain_openai import AzureOpenAIEmbeddings

            embedder = AzureOpenAIEmbeddings(
                azure_endpoint=settings.dial_endpoint,
                azure_deployment=settings.dial_embedding_deployment,
                api_version=settings.dial_api_version,
                api_key=settings.dial_api_key,
                default_headers={"Api-Key": settings.dial_api_key},
            )
            # Hard 30s timeout on the embedding API call to prevent silent hangs
            vector = await asyncio.wait_for(
                embedder.aembed_query(query_text),
                timeout=30.0,
            )

            hits = await asyncio.wait_for(
                client.search(
                    collection_name="support_ticket_embeddings",
                    query_vector=vector,
                    query_filter=qdrant_filter,
                    limit=5,
                    with_payload=True,
                ),
                timeout=10.0,
            )
            await client.close()

        except Exception as exc:
            return {"error": f"Qdrant search failed: {exc!s}"}

        results = [
            {
                "rank": i + 1,
                "ticket_id": h.payload.get("ticket_id", ""),
                "score": round(h.score, 4),
                "product_id": h.payload.get("product_id", ""),
                "ticket_category": h.payload.get("ticket_category", ""),
                "sentiment_score": h.payload.get("sentiment_score", 0.0),
                "resolution_type": h.payload.get("resolution_type", ""),
                "created_at_timestamp": h.payload.get("created_at_timestamp", 0),
            }
            for i, h in enumerate(hits)
        ]

        return {
            "query_text": query_text,
            "filters_applied": filter_metadata,
            "result_count": len(results),
            "results": results,
        }

    @mcp.tool()
    async def search_ticket_sentiments(keyword: str, date: str) -> dict:
        """Search open tickets by keyword and return matched tickets with sentiment scores.

        Performs a case-insensitive substring match against both the ``subject``
        and ``customer_text`` columns of ``customer_support_tickets`` for all
        tickets created on the specified date.  Returns matched tickets along
        with their full context and sentiment scores so the Support Agent can
        perform thematic analysis around a specific product, event, or complaint
        pattern.

        Thematic analysis use cases
        ----------------------------
        - Search ``"leather jacket"`` after a stockout event to surface all
          customer complaints referencing that product during the incident window.
        - Search ``"promo code"`` to identify a checkout coupon bug before the
          engineering team has reported it.
        - Search ``"delivery"`` to correlate customer-reported delay complaints
          with ``get_fulfillment_delay_analysis`` carrier data.

        Sentiment interpretation
        ------------------------
        The ``sentiment_score`` field (range −1.0 to 1.0) is used to rank
        matched tickets by customer distress severity:

        - ``< −0.6`` : Highly negative — customer likely to churn or escalate.
        - ``−0.6 to −0.3`` : Moderately negative — needs timely resolution.
        - ``−0.3 to 0.0`` : Mildly negative / neutral.
        - ``> 0.0`` : Positive or grateful tone (post-resolution follow-ups).

        Parameters
        ----------
        keyword : str  — Search term to match against ticket subject and body.
                  Case-insensitive.  Single-word or short phrase recommended.
        date    : str  — Calendar day in ``YYYY-MM-DD`` format.  Only tickets
                  opened on this day are searched.

        Returns
        -------
        dict
            Keys:
            - keyword          : str
            - date             : str
            - match_count      : int
            - avg_sentiment    : float | None — mean sentiment across matched tickets.
            - most_negative    : str | None — ticket_id with lowest sentiment.
            - tickets          : list[dict] — each entry has:
                  ticket_id, customer_id, product_id, subject, customer_text,
                  ticket_category, priority, ticket_status, sentiment_score,
                  resolution_type, created_at.
                  Sorted by sentiment_score ascending (most negative first).

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [SUPPORT] search_ticket_sentiments called | keyword={keyword}, date={date}")
        try:
            target = date_type.fromisoformat(date)
        except ValueError:
            return {"error": f"Invalid date format '{date}'. Expected YYYY-MM-DD."}

        day_start, day_end = _day_window(target)
        pattern = f"%{keyword}%"

        async with get_session() as session:
            from sqlalchemy import or_

            result = await session.execute(
                select(CustomerSupportTicket)
                .where(
                    CustomerSupportTicket.created_at >= day_start,
                    CustomerSupportTicket.created_at <= day_end,
                    or_(
                        CustomerSupportTicket.subject.ilike(pattern),
                        CustomerSupportTicket.customer_text.ilike(pattern),
                    ),
                )
                .order_by(CustomerSupportTicket.sentiment_score.asc())
            )
            tickets = result.scalars().all()

        if not tickets:
            return {
                "keyword": keyword,
                "date": date,
                "match_count": 0,
                "avg_sentiment": None,
                "most_negative": None,
                "tickets": [],
            }

        rows = [
            {
                "ticket_id": t.ticket_id,
                "customer_id": t.customer_id,
                "product_id": t.product_id,
                "subject": t.subject,
                "customer_text": t.customer_text,
                "ticket_category": _enum_val(t.ticket_category),
                "priority": _enum_val(t.priority),
                "ticket_status": _enum_val(t.ticket_status),
                "sentiment_score": float(t.sentiment_score),
                "resolution_type": (
                    _enum_val(t.resolution_type) if t.resolution_type else None
                ),
                "created_at": t.created_at.isoformat(),
            }
            for t in tickets
        ]
        sentiments = [r["sentiment_score"] for r in rows]
        avg_sentiment = round(sum(sentiments) / len(sentiments), 3)
        most_negative = rows[0]["ticket_id"]

        return {
            "keyword": keyword,
            "date": date,
            "match_count": len(rows),
            "avg_sentiment": avg_sentiment,
            "most_negative": most_negative,
            "tickets": rows,
        }

    @mcp.tool()
    async def get_product_return_reasons(product_id: str) -> dict:
        """Return a resolution-type percentage breakdown for all resolved tickets on a product.

        Queries ``customer_support_tickets`` filtering by the given ``product_id``
        and ``ticket_status = RESOLVED``.  Groups resolved tickets by
        ``resolution_type`` to produce a percentage distribution of how customer
        complaints about this product were closed.

        This breakdown helps the Support Agent determine whether a product's
        negative revenue trend is driven by **quality failures** (high
        REPLACEMENT_SENT and ISSUED_REFUND rates) or **description/expectation
        mismatch** (high STORE_CREDIT and COUPON_FIXED rates, indicating the
        customer kept the product but was compensated).

        Resolution type interpretation
        --------------------------------
        - ``ISSUED_REFUND``     : Customer returned product — hard revenue reversal.
        - ``REPLACEMENT_SENT``  : Product defect confirmed — quality control flag.
        - ``COUPON_FIXED``      : Coupon or checkout error — platform/tech bug signal.
        - ``STORE_CREDIT``      : Customer retained product — softer dissatisfaction.

        Parameters
        ----------
        product_id : str — Product primary key (e.g., ``'PROD-LJ-001'``).

        Returns
        -------
        dict
            Keys:
            - product_id         : str
            - total_resolved     : int — count of resolved tickets for this product.
            - total_open         : int — count of still-open tickets.
            - resolution_breakdown : list[dict] — each entry has:
                  resolution_type, count, share_pct.
                  Sorted by count descending.
            - dominant_reason    : str | None — resolution_type with highest count.
            - quality_flag       : bool — True if ISSUED_REFUND + REPLACEMENT_SENT
                                   together exceed 50% of resolved tickets.
            - avg_sentiment      : float | None — mean sentiment across all tickets
                                   for this product (any status).
        """
        log.info(f"📞 [SUPPORT] get_product_return_reasons called | product_id={product_id}")
        async with get_session() as session:
            result = await session.execute(
                select(CustomerSupportTicket).where(
                    CustomerSupportTicket.product_id == product_id
                )
            )
            tickets = result.scalars().all()

        if not tickets:
            return {
                "product_id": product_id,
                "total_resolved": 0,
                "total_open": 0,
                "resolution_breakdown": [],
                "dominant_reason": None,
                "quality_flag": False,
                "avg_sentiment": None,
            }

        resolved = [t for t in tickets if _enum_val(t.ticket_status) == "RESOLVED"]
        open_count = len(tickets) - len(resolved)

        resolution_counts: dict[str, int] = {}
        for t in resolved:
            rt = _enum_val(t.resolution_type) if t.resolution_type else "UNSPECIFIED"
            resolution_counts[rt] = resolution_counts.get(rt, 0) + 1

        total_resolved = len(resolved)
        breakdown = sorted(
            [
                {
                    "resolution_type": rt,
                    "count": cnt,
                    "share_pct": round((cnt / total_resolved) * 100, 2) if total_resolved > 0 else 0.0,
                }
                for rt, cnt in resolution_counts.items()
            ],
            key=lambda x: -x["count"],
        )

        dominant = breakdown[0]["resolution_type"] if breakdown else None
        hard_return_count = sum(
            c for rt, c in resolution_counts.items()
            if rt in ("ISSUED_REFUND", "REPLACEMENT_SENT")
        )
        quality_flag = (
            (hard_return_count / total_resolved) > 0.5
            if total_resolved > 0
            else False
        )

        sentiments = [float(t.sentiment_score) for t in tickets]
        avg_sentiment = round(sum(sentiments) / len(sentiments), 3) if sentiments else None

        return {
            "product_id": product_id,
            "total_resolved": total_resolved,
            "total_open": open_count,
            "resolution_breakdown": breakdown,
            "dominant_reason": dominant,
            "quality_flag": quality_flag,
            "avg_sentiment": avg_sentiment,
        }

    @mcp.tool()
    async def get_fulfillment_delay_analysis(target_date: str) -> dict:
        """Return orders where actual delivery exceeded the estimated delivery date.

        Queries ``order_items`` for all rows where ``actual_delivery`` is not
        NULL and ``actual_delivery > estimated_delivery``, filtered to orders
        whose ``created_at`` falls on the specified calendar day.

        This tool cross-validates customer-reported shipping delay complaints
        (surfaced via ``get_support_ticket_metrics``) against the actual
        logistics pipeline data.  A high volume of delay-flagged orders
        concentrated in a specific ``shipping_country`` or ``shipping_state``
        confirms a regional carrier disruption rather than a random fulfilment
        issue.

        Delay severity classification
        ------------------------------
        Each delayed order is tagged with a ``delay_severity`` field:

        - ``MINOR``    : 1 day late.
        - ``MODERATE`` : 2–3 days late.
        - ``SEVERE``   : 4–7 days late.
        - ``CRITICAL`` : > 7 days late.

        The response includes a regional grouping to help the Support Agent
        identify carrier-specific or geography-specific bottlenecks.

        Parameters
        ----------
        target_date : str — Calendar day (``YYYY-MM-DD``) of order creation.
                      Orders created on this date that are delayed are returned.

        Returns
        -------
        dict
            Keys:
            - date               : str
            - total_delayed      : int — count of delayed order lines.
            - avg_delay_days     : float | None
            - severity_breakdown : dict — {MINOR/MODERATE/SEVERE/CRITICAL: count}
            - regional_summary   : list[dict] — grouped by shipping_country,
                                   each with: country, delayed_count, avg_delay_days.
            - delayed_orders     : list[dict] — each entry has:
                  line_item_id, order_id, product_id, shipping_country,
                  shipping_state, estimated_delivery, actual_delivery,
                  delay_days, delay_severity.

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [SUPPORT] get_fulfillment_delay_analysis called | target_date={target_date}")
        try:
            target = date_type.fromisoformat(target_date)
        except ValueError:
            return {"error": f"Invalid date format '{target_date}'. Expected YYYY-MM-DD."}

        day_start, day_end = _day_window(target)

        async with get_session() as session:
            result = await session.execute(
                select(OrderItem).where(
                    OrderItem.created_at >= day_start,
                    OrderItem.created_at <= day_end,
                    OrderItem.actual_delivery.is_not(None),
                    OrderItem.actual_delivery > OrderItem.estimated_delivery,
                )
                .order_by(OrderItem.shipping_country)
            )
            rows = result.scalars().all()

        def _severity(days: int) -> str:
            if days == 1:
                return "MINOR"
            if days <= 3:
                return "MODERATE"
            if days <= 7:
                return "SEVERE"
            return "CRITICAL"

        delayed_orders = []
        severity_counts: dict[str, int] = {"MINOR": 0, "MODERATE": 0, "SEVERE": 0, "CRITICAL": 0}
        regional: dict[str, list[int]] = {}

        for r in rows:
            delay = (r.actual_delivery - r.estimated_delivery).days
            sev = _severity(delay)
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
            regional.setdefault(r.shipping_country, []).append(delay)
            delayed_orders.append(
                {
                    "line_item_id": r.line_item_id,
                    "order_id": r.order_id,
                    "product_id": r.product_id,
                    "shipping_country": r.shipping_country,
                    "shipping_state": r.shipping_state,
                    "estimated_delivery": r.estimated_delivery.isoformat(),
                    "actual_delivery": r.actual_delivery.isoformat(),
                    "delay_days": delay,
                    "delay_severity": sev,
                }
            )

        all_delays = [o["delay_days"] for o in delayed_orders]
        avg_delay = round(sum(all_delays) / len(all_delays), 2) if all_delays else None

        regional_summary = sorted(
            [
                {
                    "country": country,
                    "delayed_count": len(delays),
                    "avg_delay_days": round(sum(delays) / len(delays), 2),
                }
                for country, delays in regional.items()
            ],
            key=lambda x: -x["delayed_count"],
        )

        return {
            "date": target_date,
            "total_delayed": len(delayed_orders),
            "avg_delay_days": avg_delay,
            "severity_breakdown": severity_counts,
            "regional_summary": regional_summary,
            "delayed_orders": delayed_orders,
        }

    # ----------------------------------------------------------------------- #
    #  WRITE / ACTION TOOLS  (HITL-gated)                                      #
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    async def create_priority_dev_ticket(title: str, description: str) -> dict:
        """Log a verified technical bug or platform incident into the engineering escalation queue.

        This is the Support Agent's escalation write tool.  It generates a
        system-tracked engineering ticket with a unique ``BUG-XXXX`` identifier
        and **persists it as a row in** ``customer_support_tickets`` so that the
        record survives restarts, appears in DBeaver, and is queryable by other
        tools.

        The inserted row uses the following conventions:
        - ``ticket_id``       : ``BUG-<4-hex>`` (e.g., ``BUG-A3F1``)
        - ``customer_id``     : ``"SYSTEM"`` — flags this as an internal escalation.
        - ``subject``         : ``title`` parameter.
        - ``customer_text``   : ``description`` parameter.
        - ``ticket_category`` : ``Checkout_Error`` — broadest platform-failure category.
        - ``priority``        : ``CRITICAL``
        - ``ticket_status``   : ``ESCALATED`` — immediately routed to engineering queue.
        - ``sentiment_score`` : ``-1.00`` — system-generated tickets are always high-urgency.
        - ``product_id``      : NULL (not item-specific).
        - ``order_id``        : NULL.
        - ``resolution_type`` : NULL (unresolved at creation).

        This tool **must only be invoked from within the**
        ``execute_approved_actions`` **node** after explicit human approval.
        The Support Agent may *propose* creating a dev ticket during its analysis
        cycle by posting the action to the whiteboard — it must not call this
        tool directly in the reflection loop.

        When to propose a dev ticket
        ------------------------------
        - ``get_payment_gateway_performance`` confirms a gateway-specific failure
          that has persisted for more than 30 minutes (not transient).
        - ``get_order_device_breakdown`` shows Mobile_App completions at zero for
          a sustained period while Desktop is healthy.
        - ``search_ticket_sentiments`` returns a cluster of Checkout_Error tickets
          pointing to the same error message or flow step.
        - ``get_support_ticket_metrics`` reveals a CRITICAL priority spike with
          no known infrastructure cause.

        Parameters
        ----------
        title       : str — Short one-line summary of the bug or incident
                      (e.g., ``"Mobile_App checkout button unresponsive — iOS 17"``).
        description : str — Detailed reproduction steps, affected metrics,
                      supporting data references, and proposed severity level.

        Returns
        -------
        dict
            Keys:
            - success      : bool
            - bug_id       : str — e.g., ``'BUG-A3F1'``
            - title        : str
            - description  : str
            - created_at   : str — ISO-8601 UTC timestamp of ticket creation.
            - message      : str — human-readable confirmation with tracking ID.

            Returns ``{"success": False, "error": "..."}`` if the DB write fails.
        """
        log.info(f"📞 [SUPPORT] create_priority_dev_ticket called | title={title[:50]}")
        from decimal import Decimal as _Decimal

        bug_id = "BUG-" + uuid.uuid4().hex[:4].upper()
        created_at = datetime.utcnow()

        ticket = CustomerSupportTicket(
            ticket_id=bug_id,
            customer_id="SYSTEM",
            order_id=None,
            product_id=None,
            subject=title[:255],
            customer_text=description,
            ticket_category=TicketCategory.CHECKOUT_ERROR,
            priority=TicketPriority.CRITICAL,
            ticket_status=TicketStatus.ESCALATED,
            sentiment_score=_Decimal("-1.00"),
            assigned_agent_id="SYSTEM",
            resolution_type=None,
            created_at=created_at,
            resolved_at=None,
        )

        try:
            async with get_session() as session:
                session.add(ticket)
                await session.commit()
        except Exception as exc:
            return {"success": False, "error": f"DB write failed: {exc!s}"}

        return {
            "success": True,
            "bug_id": bug_id,
            "title": title,
            "description": description,
            "created_at": created_at.isoformat(),
            "message": (
                f"Priority engineering ticket '{bug_id}' created and persisted to database.  "
                f"Title: '{title}'.  "
                f"Status: ESCALATED — pending triage by the on-call engineering team.  "
                f"Tracking ID: {bug_id}."
            ),
        }
