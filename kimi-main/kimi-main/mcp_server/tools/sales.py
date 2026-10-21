"""Sales-domain MCP tools.

All six tools in this module are **read-only** and interact exclusively
with the ``order_items`` table.

Tools
-----
- get_sales_metrics_trend          : Daily revenue / volume / AOV breakdown over a date range.
- get_hourly_order_volume          : Hour-by-hour successful checkout counts for one day.
- get_top_revenue_contributors     : Products ranked by net revenue contribution over a range.
- get_regional_sales_breakdown     : Order volume and revenue mapped by country/state.
- get_payment_gateway_performance  : Transaction counts split by gateway and payment status.
- get_order_device_breakdown       : Order completions and revenue by checkout device channel.

Registration
------------
Called once during server startup via::

    from mcp_server.tools.sales import register
    register(mcp)
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime

from sqlalchemy import Float
from sqlalchemy import case
from sqlalchemy import cast
from sqlalchemy import func
from sqlalchemy import select

from app.db.models.sales import CheckoutDevice
from app.db.models.sales import OrderItem
from app.db.models.sales import PaymentGateway
from app.db.models.sales import PaymentStatus
from app.db.session import get_session

log = logging.getLogger(__name__)


def register(mcp) -> None:
    """Register all sales-domain tools onto the provided FastMCP instance.

    Parameters
    ----------
    mcp : FastMCP
        The shared FastMCP application instance created in ``mcp_server.server``.
    """

    # ----------------------------------------------------------------------- #
    #  Helper                                                                  #
    # ----------------------------------------------------------------------- #

    def _parse_date(value: str, field_name: str) -> date_type | dict:
        try:
            return date_type.fromisoformat(value)
        except ValueError:
            return {"error": f"Invalid {field_name} format '{value}'. Expected YYYY-MM-DD."}

    def _day_window(d: date_type) -> tuple[datetime, datetime]:
        return (
            datetime(d.year, d.month, d.day, 0, 0, 0),
            datetime(d.year, d.month, d.day, 23, 59, 59),
        )

    # ----------------------------------------------------------------------- #
    #  READ TOOLS                                                              #
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    async def get_sales_metrics_trend(start_date: str, end_date: str) -> dict:
        """Return a daily revenue and volume trend for a date range.

        Aggregates the ``order_items`` table across the requested window and
        returns one summary row per calendar day.  Only orders whose
        ``payment_status`` is ``SUCCESS`` are included in revenue and AOV
        calculations; ``FAILED``, ``REFUNDED``, and ``CHARGEBACK`` rows are
        counted separately so the agent can distinguish gross from net health.

        Metrics returned per day
        ------------------------
        - date                : str — ``YYYY-MM-DD`` calendar day.
        - total_orders        : int — count of all order lines (any payment status).
        - successful_orders   : int — lines where payment_status = SUCCESS.
        - failed_orders       : int — lines where payment_status = FAILED.
        - gross_revenue       : str — sum of ``gross_revenue`` on SUCCESS lines.
        - aov                 : str — Average Order Value = gross_revenue /
                                successful_orders.  ``"0.00"`` when no successes.
        - conversion_rate_pct : float — successful_orders / total_orders × 100,
                                rounded to 2 dp.  A drop here signals a checkout
                                funnel or payment-layer failure rather than a
                                demand problem.

        Parameters
        ----------
        start_date : str — Inclusive start of the window (``YYYY-MM-DD``).
        end_date   : str — Inclusive end of the window (``YYYY-MM-DD``).

        Returns
        -------
        dict
            Keys:
            - start_date        : str
            - end_date          : str
            - total_days        : int
            - days              : list[dict] — one entry per calendar day (see above).
            - window_summary    : dict — aggregate totals across the full range:
                  total_orders, successful_orders, gross_revenue, aov.

            Returns ``{"error": "..."}`` on invalid date formats or if
            start_date is after end_date.
        """
        log.info(f"[SALES] get_sales_metrics_trend called | start_date={start_date}, end_date={end_date}")
        start = _parse_date(start_date, "start_date")
        if isinstance(start, dict):
            return start
        end = _parse_date(end_date, "end_date")
        if isinstance(end, dict):
            return end
        if start > end:
            return {"error": "start_date must be on or before end_date."}

        window_start = datetime(start.year, start.month, start.day, 0, 0, 0)
        window_end = datetime(end.year, end.month, end.day, 23, 59, 59)

        async with get_session() as session:
            result = await session.execute(
                select(
                    func.date(OrderItem.created_at).label("day"),
                    func.count().label("total_orders"),
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.SUCCESS, 1), else_=0)
                    ).label("successful_orders"),
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.FAILED, 1), else_=0)
                    ).label("failed_orders"),
                    func.coalesce(
                        func.sum(
                            case(
                                (OrderItem.payment_status == PaymentStatus.SUCCESS,
                                 OrderItem.gross_revenue),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("gross_revenue"),
                )
                .where(
                    OrderItem.created_at >= window_start,
                    OrderItem.created_at <= window_end,
                )
                .group_by(func.date(OrderItem.created_at))
                .order_by(func.date(OrderItem.created_at).asc())
            )
            rows = result.all()

        days = []
        for r in rows:
            total = int(r.total_orders)
            success = int(r.successful_orders)
            revenue = float(r.gross_revenue)
            aov = round(revenue / success, 2) if success > 0 else 0.0
            conv = round((success / total) * 100, 2) if total > 0 else 0.0
            days.append(
                {
                    "date": str(r.day),
                    "total_orders": total,
                    "successful_orders": success,
                    "failed_orders": int(r.failed_orders),
                    "gross_revenue": f"{revenue:.2f}",
                    "aov": f"{aov:.2f}",
                    "conversion_rate_pct": conv,
                }
            )

        total_orders_w = sum(d["total_orders"] for d in days)
        success_orders_w = sum(d["successful_orders"] for d in days)
        gross_rev_w = sum(float(d["gross_revenue"]) for d in days)
        aov_w = round(gross_rev_w / success_orders_w, 2) if success_orders_w > 0 else 0.0

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_days": len(days),
            "days": days,
            "window_summary": {
                "total_orders": total_orders_w,
                "successful_orders": success_orders_w,
                "gross_revenue": f"{gross_rev_w:.2f}",
                "aov": f"{aov_w:.2f}",
            },
        }

    @mcp.tool()
    async def get_hourly_order_volume(target_date: str) -> dict:
        """Return a complete hour-by-hour order checkout breakdown for a single day.

        Aggregates ``order_items`` by the hour component of ``created_at`` for
        the given calendar day.  Every hour from 0 to 23 is always present in
        the response — hours with zero activity are explicitly included as
        ``{"hour": N, "successful_orders": 0, "gross_revenue": "0.00"}`` rather
        than omitted.  This guarantees the Sales Agent can detect flat-lines
        (a run of consecutive zero-order hours) without needing to infer gaps.

        Revenue figures include only ``payment_status = SUCCESS`` lines.
        Failed, refunded, and chargeback transactions are counted separately
        to distinguish demand collapse from payment-layer failure.

        Diagnostic signals
        ------------------
        - A sudden drop to zero at a specific hour with no recovery →
          likely a checkout system or payment gateway outage.
        - A gradual decline starting from a particular hour →
          likely a campaign ending, stock running out, or organic demand shift.
        - A spike in failed_orders at a specific hour →
          payment processor incident; cross-reference with
          ``get_payment_gateway_performance``.

        Parameters
        ----------
        target_date : str — Calendar day in ``YYYY-MM-DD`` format.

        Returns
        -------
        dict
            Keys:
            - date              : str
            - peak_hour         : int — hour with highest successful order count.
            - peak_order_count  : int
            - total_successful  : int — day-level successful order total.
            - total_revenue     : str — day-level gross revenue (SUCCESS only).
            - hours             : list[dict] — 24 entries (hour 0–23), each with:
                  hour, successful_orders, failed_orders, gross_revenue (str).

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [SALES] get_hourly_order_volume called | target_date={target_date}")
        parsed = _parse_date(target_date, "target_date")
        if isinstance(parsed, dict):
            return parsed
        day_start, day_end = _day_window(parsed)

        async with get_session() as session:
            result = await session.execute(
                select(
                    func.extract("hour", OrderItem.created_at).label("hour"),
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.SUCCESS, 1), else_=0)
                    ).label("successful_orders"),
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.FAILED, 1), else_=0)
                    ).label("failed_orders"),
                    func.coalesce(
                        func.sum(
                            case(
                                (OrderItem.payment_status == PaymentStatus.SUCCESS,
                                 OrderItem.gross_revenue),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("gross_revenue"),
                )
                .where(
                    OrderItem.created_at >= day_start,
                    OrderItem.created_at <= day_end,
                )
                .group_by(func.extract("hour", OrderItem.created_at))
                .order_by(func.extract("hour", OrderItem.created_at).asc())
            )
            rows = result.all()

        hour_map = {int(r.hour): r for r in rows}
        hours = []
        for h in range(24):
            r = hour_map.get(h)
            hours.append(
                {
                    "hour": h,
                    "successful_orders": int(r.successful_orders) if r else 0,
                    "failed_orders": int(r.failed_orders) if r else 0,
                    "gross_revenue": f"{float(r.gross_revenue):.2f}" if r else "0.00",
                }
            )

        total_successful = sum(h["successful_orders"] for h in hours)
        total_revenue = sum(float(h["gross_revenue"]) for h in hours)
        peak = max(hours, key=lambda h: h["successful_orders"])

        return {
            "date": target_date,
            "peak_hour": peak["hour"],
            "peak_order_count": peak["successful_orders"],
            "total_successful": total_successful,
            "total_revenue": f"{total_revenue:.2f}",
            "hours": hours,
        }

    @mcp.tool()
    async def get_top_revenue_contributors(start_date: str, end_date: str) -> dict:
        """Return products ranked by their net revenue contribution over a date range.

        Aggregates ``order_items`` grouped by ``product_id`` and joins back to
        ``products_inventory`` for human-readable product titles.  Only
        ``payment_status = SUCCESS`` lines are included in revenue figures.

        This tool is the primary lens for distinguishing a systemic market
        downturn from a localised single-product failure.  If one product
        accounts for a disproportionate share of revenue and shows a steep
        week-on-week decline, the root cause analysis should focus on that
        product's inventory, campaign, and support ticket history rather than
        treating the issue as store-wide.

        Metrics per product
        -------------------
        - rank              : int — 1-indexed position sorted by gross_revenue desc.
        - product_id        : str
        - title             : str — product name from ``products_inventory``.
        - total_orders      : int — successful order line count.
        - total_units_sold  : int — sum of ``quantity`` on SUCCESS lines.
        - gross_revenue     : str — total net revenue (SUCCESS lines only).
        - revenue_share_pct : float — this product's revenue as a % of window total.
        - avg_discount      : str — mean ``discount_applied`` across SUCCESS lines.

        Parameters
        ----------
        start_date : str — Inclusive window start (``YYYY-MM-DD``).
        end_date   : str — Inclusive window end (``YYYY-MM-DD``).

        Returns
        -------
        dict
            Keys:
            - start_date       : str
            - end_date         : str
            - window_revenue   : str — total gross revenue across all products.
            - product_count    : int — distinct products with sales in the window.
            - products         : list[dict] — ranked list (see metrics above).

            Returns ``{"error": "..."}`` on invalid dates or reversed range.
        """
        log.info(f"📞 [SALES] get_top_revenue_contributors called | start_date={start_date}, end_date={end_date}")
        from app.db.models.catalog import ProductInventory

        start = _parse_date(start_date, "start_date")
        if isinstance(start, dict):
            return start
        end = _parse_date(end_date, "end_date")
        if isinstance(end, dict):
            return end
        if start > end:
            return {"error": "start_date must be on or before end_date."}

        window_start = datetime(start.year, start.month, start.day, 0, 0, 0)
        window_end = datetime(end.year, end.month, end.day, 23, 59, 59)

        async with get_session() as session:
            result = await session.execute(
                select(
                    OrderItem.product_id,
                    ProductInventory.title,
                    func.count().label("total_orders"),
                    func.sum(OrderItem.quantity).label("total_units_sold"),
                    func.coalesce(func.sum(OrderItem.gross_revenue), 0).label("gross_revenue"),
                    func.coalesce(func.avg(OrderItem.discount_applied), 0).label("avg_discount"),
                )
                .join(
                    ProductInventory,
                    OrderItem.product_id == ProductInventory.product_id,
                )
                .where(
                    OrderItem.payment_status == PaymentStatus.SUCCESS,
                    OrderItem.created_at >= window_start,
                    OrderItem.created_at <= window_end,
                )
                .group_by(OrderItem.product_id, ProductInventory.title)
                .order_by(func.sum(OrderItem.gross_revenue).desc())
            )
            rows = result.all()

        window_revenue = sum(float(r.gross_revenue) for r in rows)
        products = []
        for i, r in enumerate(rows, start=1):
            rev = float(r.gross_revenue)
            share = round((rev / window_revenue) * 100, 2) if window_revenue > 0 else 0.0
            products.append(
                {
                    "rank": i,
                    "product_id": r.product_id,
                    "title": r.title,
                    "total_orders": int(r.total_orders),
                    "total_units_sold": int(r.total_units_sold),
                    "gross_revenue": f"{rev:.2f}",
                    "revenue_share_pct": share,
                    "avg_discount": f"{float(r.avg_discount):.2f}",
                }
            )

        return {
            "start_date": start_date,
            "end_date": end_date,
            "window_revenue": f"{window_revenue:.2f}",
            "product_count": len(products),
            "products": products,
        }

    @mcp.tool()
    async def get_regional_sales_breakdown(target_date: str) -> dict:
        """Return order volume and revenue mapped by shipping country and state for a day.

        Aggregates ``order_items`` grouped by ``shipping_country`` and
        ``shipping_state`` for the specified calendar day.  Only
        ``payment_status = SUCCESS`` lines are counted in revenue; failed
        transactions are surfaced separately per region to identify payment
        routing problems that may be carrier- or bank-specific.

        Regional failures are often invisible in store-wide metrics — a country
        with intermittent courier disruption may see SUCCESS rates remain stable
        while order volumes silently decline.  The Sales Agent surfaces regional
        anomalies onto the whiteboard for the Support Agent to cross-reference
        against open ``SHIPPING_DELAY`` tickets in the same geography.

        Metrics per region
        ------------------
        - country           : str
        - state             : str
        - successful_orders : int
        - failed_orders     : int
        - gross_revenue     : str — SUCCESS lines only.
        - avg_shipping_cost : str — mean ``shipping_cost`` for the region.

        Parameters
        ----------
        target_date : str — Calendar day in ``YYYY-MM-DD`` format.

        Returns
        -------
        dict
            Keys:
            - date              : str
            - region_count      : int — distinct country/state combinations.
            - top_country       : str — country with highest gross revenue.
            - regions           : list[dict] — sorted by gross_revenue desc.

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [SALES] get_regional_sales_breakdown called | target_date={target_date}")
        parsed = _parse_date(target_date, "target_date")
        if isinstance(parsed, dict):
            return parsed
        day_start, day_end = _day_window(parsed)

        async with get_session() as session:
            result = await session.execute(
                select(
                    OrderItem.shipping_country,
                    OrderItem.shipping_state,
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.SUCCESS, 1), else_=0)
                    ).label("successful_orders"),
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.FAILED, 1), else_=0)
                    ).label("failed_orders"),
                    func.coalesce(
                        func.sum(
                            case(
                                (OrderItem.payment_status == PaymentStatus.SUCCESS,
                                 OrderItem.gross_revenue),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("gross_revenue"),
                    func.coalesce(func.avg(OrderItem.shipping_cost), 0).label("avg_shipping_cost"),
                )
                .where(
                    OrderItem.created_at >= day_start,
                    OrderItem.created_at <= day_end,
                )
                .group_by(OrderItem.shipping_country, OrderItem.shipping_state)
                .order_by(func.sum(OrderItem.gross_revenue).desc())
            )
            rows = result.all()

        regions = [
            {
                "country": r.shipping_country,
                "state": r.shipping_state,
                "successful_orders": int(r.successful_orders),
                "failed_orders": int(r.failed_orders),
                "gross_revenue": f"{float(r.gross_revenue):.2f}",
                "avg_shipping_cost": f"{float(r.avg_shipping_cost):.2f}",
            }
            for r in rows
        ]
        top_country = regions[0]["country"] if regions else "N/A"

        return {
            "date": target_date,
            "region_count": len(regions),
            "top_country": top_country,
            "regions": regions,
        }

    @mcp.tool()
    async def get_payment_gateway_performance(target_date: str) -> dict:
        """Return transaction counts split by payment gateway and settlement status for a day.

        Aggregates ``order_items`` grouped by ``payment_gateway`` ×
        ``payment_status`` for the specified calendar day.  Returns one summary
        block per gateway (Stripe, PayPal, Razorpay) containing the full
        breakdown of SUCCESS, FAILED, REFUNDED, and CHARGEBACK counts alongside
        total attempted revenue and successfully collected revenue.

        This is the fastest way to isolate external payment API incidents:
        - Stripe SUCCESS rate drops to 0% at a specific hour while PayPal
          remains stable → Stripe API outage; cross-reference with
          ``get_hourly_order_volume`` for exact onset minute.
        - All gateways show FAILED spikes → bank authentication service issue
          or 3DS enforcement change.
        - CHARGEBACK spike for one gateway → fraud pattern; requires manual review.

        Metrics per gateway
        -------------------
        - gateway              : str — ``Stripe`` | ``PayPal`` | ``Razorpay``.
        - total_attempts       : int — all transaction lines through this gateway.
        - successful           : int
        - failed               : int
        - refunded             : int
        - chargeback           : int
        - success_rate_pct     : float — successful / total_attempts × 100.
        - attempted_revenue    : str — sum of gross_revenue for ALL statuses.
        - collected_revenue    : str — sum of gross_revenue for SUCCESS only.
        - revenue_lost_pct     : float — (attempted − collected) / attempted × 100.

        Parameters
        ----------
        target_date : str — Calendar day in ``YYYY-MM-DD`` format.

        Returns
        -------
        dict
            Keys:
            - date          : str
            - gateways      : list[dict] — one entry per gateway with data (see above).
            - healthiest    : str — gateway with highest success_rate_pct.
            - most_failures : str — gateway with highest absolute failed count.

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [SALES] get_payment_gateway_performance called | target_date={target_date}")
        parsed = _parse_date(target_date, "target_date")
        if isinstance(parsed, dict):
            return parsed
        day_start, day_end = _day_window(parsed)

        async with get_session() as session:
            result = await session.execute(
                select(
                    OrderItem.payment_gateway,
                    OrderItem.payment_status,
                    func.count().label("count"),
                    func.coalesce(func.sum(OrderItem.gross_revenue), 0).label("revenue"),
                )
                .where(
                    OrderItem.created_at >= day_start,
                    OrderItem.created_at <= day_end,
                )
                .group_by(OrderItem.payment_gateway, OrderItem.payment_status)
            )
            rows = result.all()

        # Pivot into per-gateway summaries
        gateway_map: dict[str, dict] = {}
        for r in rows:
            gw = r.payment_gateway.value if hasattr(r.payment_gateway, "value") else str(r.payment_gateway)
            st = r.payment_status.value if hasattr(r.payment_status, "value") else str(r.payment_status)
            if gw not in gateway_map:
                gateway_map[gw] = {
                    "gateway": gw,
                    "total_attempts": 0,
                    "successful": 0,
                    "failed": 0,
                    "refunded": 0,
                    "chargeback": 0,
                    "attempted_revenue": 0.0,
                    "collected_revenue": 0.0,
                }
            gateway_map[gw]["total_attempts"] += int(r.count)
            gateway_map[gw]["attempted_revenue"] += float(r.revenue)
            if st == "SUCCESS":
                gateway_map[gw]["successful"] += int(r.count)
                gateway_map[gw]["collected_revenue"] += float(r.revenue)
            elif st == "FAILED":
                gateway_map[gw]["failed"] += int(r.count)
            elif st == "REFUNDED":
                gateway_map[gw]["refunded"] += int(r.count)
            elif st == "CHARGEBACK":
                gateway_map[gw]["chargeback"] += int(r.count)

        gateways = []
        for g in gateway_map.values():
            total = g["total_attempts"]
            attempted = g["attempted_revenue"]
            collected = g["collected_revenue"]
            success_rate = round((g["successful"] / total) * 100, 2) if total > 0 else 0.0
            revenue_lost_pct = (
                round(((attempted - collected) / attempted) * 100, 2)
                if attempted > 0
                else 0.0
            )
            gateways.append(
                {
                    "gateway": g["gateway"],
                    "total_attempts": total,
                    "successful": g["successful"],
                    "failed": g["failed"],
                    "refunded": g["refunded"],
                    "chargeback": g["chargeback"],
                    "success_rate_pct": success_rate,
                    "attempted_revenue": f"{attempted:.2f}",
                    "collected_revenue": f"{collected:.2f}",
                    "revenue_lost_pct": revenue_lost_pct,
                }
            )
        gateways.sort(key=lambda g: g["collected_revenue"], reverse=True)

        healthiest = (
            max(gateways, key=lambda g: g["success_rate_pct"])["gateway"]
            if gateways else "N/A"
        )
        most_failures = (
            max(gateways, key=lambda g: g["failed"])["gateway"]
            if gateways else "N/A"
        )

        return {
            "date": target_date,
            "gateways": gateways,
            "healthiest": healthiest,
            "most_failures": most_failures,
        }

    @mcp.tool()
    async def get_order_device_breakdown(target_date: str) -> dict:
        """Return order completions and revenue split by checkout device channel for a day.

        Aggregates ``order_items`` grouped by ``checkout_device`` for the given
        calendar day.  All three channels are always represented in the response
        (Mobile_App, Mobile_Web, Desktop) — a channel with zero activity appears
        with all-zero counts rather than being omitted.

        This tool isolates front-end platform failures that are invisible in
        aggregate revenue figures.  A fully functional desktop checkout combined
        with zero Mobile_App completions for three consecutive hours is a strong
        signal of a native app deployment issue or push-notification failure
        rather than a demand problem.

        Agents should correlate Mobile_App drops with marketing campaign data
        (most TikTok and social campaigns route users to the mobile app) and
        Support ticket data (checkout error tickets originating from mobile
        customer IDs).

        Metrics per device
        ------------------
        - device              : str — ``Mobile_App`` | ``Mobile_Web`` | ``Desktop``.
        - total_orders        : int — all order lines (any payment status).
        - successful_orders   : int — SUCCESS payment status only.
        - failed_orders       : int — FAILED payment status only.
        - gross_revenue       : str — SUCCESS revenue only.
        - revenue_share_pct   : float — device revenue as % of daily total.
        - avg_order_value     : str — gross_revenue / successful_orders.

        Parameters
        ----------
        target_date : str — Calendar day in ``YYYY-MM-DD`` format.

        Returns
        -------
        dict
            Keys:
            - date              : str
            - dominant_channel  : str — device with highest gross revenue.
            - devices           : list[dict] — all 3 channels sorted by
                                  gross_revenue desc.

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [SALES] get_order_device_breakdown called | target_date={target_date}")
        parsed = _parse_date(target_date, "target_date")
        if isinstance(parsed, dict):
            return parsed
        day_start, day_end = _day_window(parsed)

        async with get_session() as session:
            result = await session.execute(
                select(
                    OrderItem.checkout_device,
                    func.count().label("total_orders"),
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.SUCCESS, 1), else_=0)
                    ).label("successful_orders"),
                    func.sum(
                        case((OrderItem.payment_status == PaymentStatus.FAILED, 1), else_=0)
                    ).label("failed_orders"),
                    func.coalesce(
                        func.sum(
                            case(
                                (OrderItem.payment_status == PaymentStatus.SUCCESS,
                                 OrderItem.gross_revenue),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("gross_revenue"),
                )
                .where(
                    OrderItem.created_at >= day_start,
                    OrderItem.created_at <= day_end,
                )
                .group_by(OrderItem.checkout_device)
            )
            rows = result.all()

        device_map = {
            d.value: {
                "device": d.value,
                "total_orders": 0,
                "successful_orders": 0,
                "failed_orders": 0,
                "gross_revenue": 0.0,
            }
            for d in CheckoutDevice
        }
        for r in rows:
            dv = r.checkout_device.value if hasattr(r.checkout_device, "value") else str(r.checkout_device)
            device_map[dv]["total_orders"] = int(r.total_orders)
            device_map[dv]["successful_orders"] = int(r.successful_orders)
            device_map[dv]["failed_orders"] = int(r.failed_orders)
            device_map[dv]["gross_revenue"] = float(r.gross_revenue)

        total_revenue = sum(d["gross_revenue"] for d in device_map.values())
        devices = []
        for d in sorted(device_map.values(), key=lambda x: x["gross_revenue"], reverse=True):
            rev = d["gross_revenue"]
            success = d["successful_orders"]
            share = round((rev / total_revenue) * 100, 2) if total_revenue > 0 else 0.0
            aov = round(rev / success, 2) if success > 0 else 0.0
            devices.append(
                {
                    "device": d["device"],
                    "total_orders": d["total_orders"],
                    "successful_orders": success,
                    "failed_orders": d["failed_orders"],
                    "gross_revenue": f"{rev:.2f}",
                    "revenue_share_pct": share,
                    "avg_order_value": f"{aov:.2f}",
                }
            )

        dominant = devices[0]["device"] if devices else "N/A"

        return {
            "date": target_date,
            "dominant_channel": dominant,
            "devices": devices,
        }
