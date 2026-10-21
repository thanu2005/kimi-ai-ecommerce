"""Marketing-domain MCP tools.

All six tools in this module interact exclusively with the
``marketing_campaigns`` and ``products_inventory`` tables.

Read tools (safe to call during any agent analysis cycle):
    - resolve_campaign_identifiers   : Fuzzy name/brand search returning campaign IDs + linked products.
    - get_campaign_performance       : Active campaigns with ROAS metrics grouped by channel.
    - check_active_promotions        : All non-paused campaigns for a date with budget burn state.
    - get_hourly_spend_distribution  : Hour-by-hour spend extracted from the hourly_spend_log JSON.

Write / action tools (must only be called from the HITL execute_approved_actions
node after explicit operator approval):
    - pause_marketing_campaign  : Sets campaign_status to PAUSED.
    - adjust_campaign_budget    : Updates the daily_budget ceiling for a campaign.
    - update_campaign_status    : Sets campaign_status to ACTIVE/PAUSED/COMPLETED/BUDGET_EXHAUSTED.
    - create_marketing_campaign : Resolves product + creates a new campaign with generated ID.

Registration
------------
Called once during server startup via::

    from mcp_server.tools.marketing import register
    register(mcp)
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import String
from sqlalchemy import cast
from sqlalchemy import update
from sqlalchemy.sql import func

from app.db.models.catalog import ProductInventory
from app.db.models.marketing import MarketingChannel
from app.db.models.marketing import CampaignStatus
from app.db.models.marketing import MarketingCampaign
from app.db.session import get_session

log = logging.getLogger(__name__)


def register(mcp) -> None:
    """Register all marketing-domain tools onto the provided FastMCP instance.

    Parameters
    ----------
    mcp : FastMCP
        The shared FastMCP application instance created in ``mcp_server.server``.
    """

    # ----------------------------------------------------------------------- #
    #  Helper                                                                  #
    # ----------------------------------------------------------------------- #

    def _day_window(d: date_type) -> tuple[datetime, datetime]:
        return (
            datetime(d.year, d.month, d.day, 0, 0, 0),
            datetime(d.year, d.month, d.day, 23, 59, 59),
        )

    def _normalize_channel(channel: str) -> MarketingChannel | str:
        """Normalize flexible channel input to MarketingChannel enum value string."""
        c = (channel or "").strip().lower().replace("-", "_").replace(" ", "_")
        mapping = {
            "facebook": "Facebook_Ads",
            "facebook_ads": "Facebook_Ads",
            "google": "Google_Ads",
            "google_ads": "Google_Ads",
            "tiktok": "TikTok_Ads",
            "tiktok_ads": "TikTok_Ads",
            "email": "Email",
        }
        return mapping.get(c, channel)

    def _campaign_prefix(channel: str) -> str:
        """Get channel prefix for campaign id generation."""
        normalized = str(_normalize_channel(channel))
        prefix_map = {
            "Facebook_Ads": "FB",
            "Google_Ads": "GG",
            "TikTok_Ads": "TT",
            "Email": "EM",
        }
        return prefix_map.get(normalized, "MK")

    # ----------------------------------------------------------------------- #
    #  READ TOOLS                                                              #
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    async def resolve_campaign_identifiers(name_or_keyword: str) -> dict:
        """Resolve a fuzzy campaign name, product reference, or channel keyword to matching marketing campaigns.

        Performs a case-insensitive substring search across ``campaign_name``,
        ``product_id``, and ``channel`` in ``marketing_campaigns``.  This is
        the semantic bridge between natural language references ("Nike summer
        promo", "Facebook campaigns", "PROD-NK-001") and the exact
        ``campaign_id`` keys required by ``pause_marketing_campaign`` and
        ``adjust_campaign_budget``.

        **This tool must be called first** whenever the user query references a
        campaign or product by name, partial ID, or channel rather than a known
        ``campaign_id``.  Do NOT guess or fabricate campaign IDs — always
        resolve them through this tool before calling any other campaign tool.

        Parameters
        ----------
        name_or_keyword : str
            Free-text campaign name, partial product_id, or channel keyword to
            search for (e.g., ``"Nike"``, ``"leather jacket"``, ``"Facebook"``,
            ``"PROD-NK"``).

        Returns
        -------
        dict
            Keys:
            - query        : str — echoed search term.
            - match_count  : int — number of matching campaigns.
            - matches      : list[dict] — each entry contains:
                  campaign_id, campaign_name, product_id, channel,
                  campaign_status, daily_budget, total_spend_today,
                  attributed_revenue.
        """
        log.info(f"📞 [MARKETING] resolve_campaign_identifiers called | name_or_keyword={name_or_keyword}")
        pattern = f"%{name_or_keyword}%"

        async with get_session() as session:
            result = await session.execute(
                select(
                    MarketingCampaign.campaign_id,
                    MarketingCampaign.campaign_name,
                    MarketingCampaign.target_product_id,
                    MarketingCampaign.channel,
                    MarketingCampaign.campaign_status,
                    MarketingCampaign.daily_budget,
                    MarketingCampaign.total_spend_today,
                    MarketingCampaign.attributed_revenue,
                ).where(
                    or_(
                        MarketingCampaign.campaign_name.ilike(pattern),
                        MarketingCampaign.target_product_id.ilike(pattern),
                        cast(MarketingCampaign.channel, String).ilike(pattern),
                    )
                ).order_by(MarketingCampaign.campaign_name.asc())
            )
            rows = result.all()

        matches = [
            {
                "campaign_id": r.campaign_id,
                "campaign_name": r.campaign_name,
                "product_id": r.target_product_id,
                "channel": r.channel.value if hasattr(r.channel, "value") else str(r.channel),
                "campaign_status": r.campaign_status.value if hasattr(r.campaign_status, "value") else str(r.campaign_status),
                "daily_budget": float(r.daily_budget),
                "total_spend_today": float(r.total_spend_today),
                "attributed_revenue": float(r.attributed_revenue),
            }
            for r in rows
        ]
        return {
            "query": name_or_keyword,
            "match_count": len(matches),
            "matches": matches,
        }

    @mcp.tool()
    async def get_campaign_performance(date: str) -> dict:
        """Return active campaign performance metrics grouped by ad channel for a given date.

        Queries ``marketing_campaigns`` joined to ``products_inventory`` for all
        campaigns whose ``created_at`` falls on or before the requested date AND
        whose ``campaign_status`` is ``ACTIVE`` or ``BUDGET_EXHAUSTED`` (i.e.,
        campaigns that were live on that day, including those that burned through
        their budget).

        For each campaign the tool computes ROAS (Return on Ad Spend) as::

            roas = attributed_revenue / total_spend_today

        A ROAS below 1.0 means the campaign is spending more than it earns in
        attributed revenue — a primary signal for budget reallocation or
        immediate pausing.

        The response groups results by ``channel`` so the Marketing Agent can
        perform platform-level analysis (e.g., all Google Ads campaigns combined
        vs all TikTok campaigns) before drilling into individual campaign IDs.

        Metrics per campaign
        --------------------
        - campaign_id        : str
        - campaign_name      : str
        - channel            : str — Facebook_Ads | Google_Ads | TikTok_Ads | Email.
        - target_product_id  : str
        - target_product     : str — product title from ``products_inventory``.
        - campaign_status    : str — ACTIVE | BUDGET_EXHAUSTED.
        - daily_budget       : str
        - total_spend_today  : str
        - budget_consumed_pct: float — total_spend_today / daily_budget × 100.
        - impressions        : int
        - clicks             : int
        - ctr                : str — click-through rate (%).
        - cpc                : str — cost per click ($).
        - attributed_revenue : str
        - roas               : float — attributed_revenue / total_spend_today.
                               ``0.0`` when spend is zero.

        Parameters
        ----------
        date : str — Calendar day in ``YYYY-MM-DD`` format.  Campaigns created
               on or before this date that were active on the day are included.

        Returns
        -------
        dict
            Keys:
            - date              : str
            - total_campaigns   : int — count of live campaigns for the day.
            - channels          : dict — keys are channel names, values are lists
                                  of campaign dicts (see metrics above).
            - overall_roas      : float — total attributed revenue / total spend
                                  across all campaigns.
            - total_spend       : str — sum of total_spend_today across campaigns.
            - total_attributed  : str — sum of attributed_revenue across campaigns.

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [MARKETING] get_campaign_performance called | date={date}")
        try:
            target = date_type.fromisoformat(date)
        except ValueError:
            return {"error": f"Invalid date format '{date}'. Expected YYYY-MM-DD."}

        cutoff = datetime(target.year, target.month, target.day, 23, 59, 59)

        async with get_session() as session:
            result = await session.execute(
                select(MarketingCampaign, ProductInventory.title)
                .join(
                    ProductInventory,
                    MarketingCampaign.target_product_id == ProductInventory.product_id,
                )
                .where(
                    MarketingCampaign.created_at <= cutoff,
                    MarketingCampaign.campaign_status.in_(
                        [CampaignStatus.ACTIVE, CampaignStatus.BUDGET_EXHAUSTED]
                    ),
                )
                .order_by(MarketingCampaign.attributed_revenue.desc())
            )
            rows = result.all()

        channels: dict[str, list] = {}
        total_spend = 0.0
        total_attributed = 0.0

        for campaign, product_title in rows:
            ch = (
                campaign.channel.value
                if hasattr(campaign.channel, "value")
                else str(campaign.channel)
            )
            status = (
                campaign.campaign_status.value
                if hasattr(campaign.campaign_status, "value")
                else str(campaign.campaign_status)
            )
            spend = float(campaign.total_spend_today)
            attributed = float(campaign.attributed_revenue)
            budget = float(campaign.daily_budget)
            roas = round(attributed / spend, 2) if spend > 0 else 0.0
            budget_pct = round((spend / budget) * 100, 2) if budget > 0 else 0.0

            total_spend += spend
            total_attributed += attributed

            entry = {
                "campaign_id": campaign.campaign_id,
                "campaign_name": campaign.campaign_name,
                "channel": ch,
                "target_product_id": campaign.target_product_id,
                "target_product": product_title,
                "campaign_status": status,
                "daily_budget": f"{budget:.2f}",
                "total_spend_today": f"{spend:.2f}",
                "budget_consumed_pct": budget_pct,
                "impressions": campaign.impressions,
                "clicks": campaign.clicks,
                "ctr": str(campaign.ctr),
                "cpc": str(campaign.cpc),
                "attributed_revenue": f"{attributed:.2f}",
                "roas": roas,
            }
            channels.setdefault(ch, []).append(entry)

        overall_roas = round(total_attributed / total_spend, 2) if total_spend > 0 else 0.0
        total_campaigns = sum(len(v) for v in channels.values())

        return {
            "date": date,
            "total_campaigns": total_campaigns,
            "channels": channels,
            "overall_roas": overall_roas,
            "total_spend": f"{total_spend:.2f}",
            "total_attributed": f"{total_attributed:.2f}",
        }

    @mcp.tool()
    async def check_active_promotions(date: str) -> dict:
        """Return all non-paused campaigns active on a given date with their budget burn state.

        This tool gives the Marketing Agent a rapid snapshot of every live
        promotion running on the requested date, including campaigns in
        ``ACTIVE``, ``BUDGET_EXHAUSTED``, and ``COMPLETED`` states.  Paused
        campaigns are intentionally excluded since they no longer affect spend.

        The primary use case is identifying promotions that are still burning
        budget despite being linked to out-of-stock products — a cross-domain
        anomaly the Marketing Agent flags to the whiteboard after the Inventory
        Agent reports a stockout timestamp.

        Budget burn state
        -----------------
        Each campaign entry includes a ``burn_state`` field:

        - ``HEALTHY``         : spend < 80% of daily_budget AND status ACTIVE.
        - ``HIGH_BURN``       : spend >= 80% and < 100% of daily_budget.
        - ``EXHAUSTED``       : campaign_status is BUDGET_EXHAUSTED.
        - ``COMPLETED``       : campaign has reached its planned end.
        - ``ZERO_SPEND``      : total_spend_today is 0.00 despite ACTIVE status —
                                signals a delivery or billing issue.

        Parameters
        ----------
        date : str — Calendar day in ``YYYY-MM-DD`` format.

        Returns
        -------
        dict
            Keys:
            - date               : str
            - active_count       : int — total non-paused campaigns.
            - high_burn_count    : int — campaigns at >= 80% budget consumed.
            - zero_spend_count   : int — active campaigns with 0 spend.
            - campaigns          : list[dict] — each entry contains:
                  campaign_id, campaign_name, channel, target_product_id,
                  campaign_status, daily_budget, total_spend_today,
                  budget_consumed_pct, attributed_revenue, roas, burn_state.

            Returns ``{"error": "..."}`` on invalid date format.
        """
        log.info(f"📞 [MARKETING] check_active_promotions called | date={date}")
        try:
            target = date_type.fromisoformat(date)
        except ValueError:
            return {"error": f"Invalid date format '{date}'. Expected YYYY-MM-DD."}

        cutoff = datetime(target.year, target.month, target.day, 23, 59, 59)
        excluded = [CampaignStatus.PAUSED]

        async with get_session() as session:
            result = await session.execute(
                select(MarketingCampaign)
                .where(
                    MarketingCampaign.created_at <= cutoff,
                    MarketingCampaign.campaign_status.not_in(excluded),
                )
                .order_by(MarketingCampaign.total_spend_today.desc())
            )
            rows = result.scalars().all()

        campaigns = []
        high_burn = 0
        zero_spend = 0

        for c in rows:
            spend = float(c.total_spend_today)
            budget = float(c.daily_budget)
            attributed = float(c.attributed_revenue)
            status = c.campaign_status.value if hasattr(c.campaign_status, "value") else str(c.campaign_status)
            budget_pct = round((spend / budget) * 100, 2) if budget > 0 else 0.0
            roas = round(attributed / spend, 2) if spend > 0 else 0.0

            if status == "BUDGET_EXHAUSTED":
                burn_state = "EXHAUSTED"
            elif status == "COMPLETED":
                burn_state = "COMPLETED"
            elif spend == 0.0 and status == "ACTIVE":
                burn_state = "ZERO_SPEND"
                zero_spend += 1
            elif budget_pct >= 80:
                burn_state = "HIGH_BURN"
                high_burn += 1
            else:
                burn_state = "HEALTHY"

            campaigns.append(
                {
                    "campaign_id": c.campaign_id,
                    "campaign_name": c.campaign_name,
                    "channel": c.channel.value if hasattr(c.channel, "value") else str(c.channel),
                    "target_product_id": c.target_product_id,
                    "campaign_status": status,
                    "daily_budget": f"{budget:.2f}",
                    "total_spend_today": f"{spend:.2f}",
                    "budget_consumed_pct": budget_pct,
                    "attributed_revenue": f"{attributed:.2f}",
                    "roas": roas,
                    "burn_state": burn_state,
                }
            )

        return {
            "date": date,
            "active_count": len(campaigns),
            "high_burn_count": high_burn,
            "zero_spend_count": zero_spend,
            "campaigns": campaigns,
        }

    @mcp.tool()
    async def get_hourly_spend_distribution(campaign_id: str) -> dict:
        """Return the hour-by-hour ad spend breakdown from a campaign's hourly_spend_log.

        Reads and parses the ``hourly_spend_log`` JSONB column for the specified
        campaign, which stores an array of ``{"hour": int, "spend": float}``
        objects recorded by the ad platform's reporting webhook.

        This is the critical cross-domain correlation tool.  Once the Inventory
        Agent reports the exact timestamp that a product went out of stock, the
        Marketing Agent calls this tool to calculate how much ad budget was
        burned in the hours *after* the stockout — money spent driving traffic
        to a product page that would return a sold-out message.

        The response includes a ``post_stockout_spend_analysis`` helper field
        that the agent populates when a stockout hour is known (passed as
        ``stockout_hour``).  If ``stockout_hour`` is not provided, the raw
        distribution is returned for the agent to analyse manually.

        Metrics returned
        ----------------
        - campaign_id         : str
        - campaign_name       : str
        - campaign_status     : str
        - total_spend_today   : str — from the campaign record (ground truth).
        - log_entry_count     : int — number of hours recorded in the JSON array.
        - log_total_spend     : str — sum of spend values in the log entries.
        - hours               : list[dict] — each entry: ``{"hour": int, "spend": float}``,
                                sorted ascending by hour.
        - peak_spend_hour     : int — hour with the highest spend value.
        - peak_spend_value    : float

        Parameters
        ----------
        campaign_id : str — Campaign primary key (e.g., ``'CAMP-TT-908'``).

        Returns
        -------
        dict
            Keys: campaign_id, campaign_name, campaign_status, total_spend_today,
            log_entry_count, log_total_spend, hours, peak_spend_hour,
            peak_spend_value.

            Returns ``{"error": "..."}`` if the campaign is not found or if
            the ``hourly_spend_log`` column is NULL / empty.
        """
        log.info(f"📞 [MARKETING] get_hourly_spend_distribution called | campaign_id={campaign_id}")
        async with get_session() as session:
            result = await session.execute(
                select(
                    MarketingCampaign.campaign_id,
                    MarketingCampaign.campaign_name,
                    MarketingCampaign.campaign_status,
                    MarketingCampaign.total_spend_today,
                    MarketingCampaign.hourly_spend_log,
                ).where(MarketingCampaign.campaign_id == campaign_id)
            )
            row = result.first()

        if row is None:
            return {"error": f"Campaign '{campaign_id}' not found."}

        log = row.hourly_spend_log
        if not log:
            return {
                "error": (
                    f"Campaign '{campaign_id}' has no hourly_spend_log data recorded yet."
                )
            }

        # Normalise entries — each entry must have "hour" (int) and "spend" (float)
        hours = sorted(
            [{"hour": int(e["hour"]), "spend": float(e.get("spend", 0.0))} for e in log],
            key=lambda x: x["hour"],
        )
        log_total = sum(h["spend"] for h in hours)
        peak = max(hours, key=lambda h: h["spend"])
        status = (
            row.campaign_status.value
            if hasattr(row.campaign_status, "value")
            else str(row.campaign_status)
        )

        return {
            "campaign_id": row.campaign_id,
            "campaign_name": row.campaign_name,
            "campaign_status": status,
            "total_spend_today": str(row.total_spend_today),
            "log_entry_count": len(hours),
            "log_total_spend": f"{log_total:.2f}",
            "hours": hours,
            "peak_spend_hour": peak["hour"],
            "peak_spend_value": peak["spend"],
        }

    # ----------------------------------------------------------------------- #
    #  WRITE / ACTION TOOLS  (HITL-gated)                                      #
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    async def pause_marketing_campaign(campaign_id: str) -> dict:
        """Set a campaign's status to PAUSED, immediately halting all ad spend.

        This is the primary financial circuit-breaker for the Marketing Agent.
        It updates ``campaign_status`` to ``PAUSED`` in ``marketing_campaigns``
        for the specified campaign ID.

        This tool **must only be invoked from within the**
        ``execute_approved_actions`` **node** after explicit human approval via
        the dashboard interrupt checkpoint.  The Marketing Agent may *propose*
        pausing a campaign during its analysis cycle by adding the action to the
        whiteboard — but it must never call this tool directly.

        When to propose pausing
        -----------------------
        - Campaign is driving traffic to a product with ``restock_status`` of
          ``BACKORDERED`` or ``BELOW_SAFETY`` and no PO arrival within 7 days.
        - Campaign ROAS has dropped below 1.0 for two or more consecutive hours.
        - ``BUDGET_EXHAUSTED`` campaign is spending carryover budget without
          attribution (platform billing lag).

        Idempotency
        -----------
        Pausing an already-PAUSED campaign is a no-op — the status remains
        ``PAUSED`` and the response includes a ``already_paused: true`` flag.
        Pausing a ``COMPLETED`` or ``BUDGET_EXHAUSTED`` campaign is permitted
        (to prevent re-activation) but triggers a warning in the response.

        Parameters
        ----------
        campaign_id : str — Campaign primary key (e.g., ``'CAMP-TT-908'``).

        Returns
        -------
        dict
            Keys:
            - success              : bool
            - campaign_id          : str
            - campaign_name        : str
            - previous_status      : str
            - new_status           : str — always ``'PAUSED'`` on success.
            - already_paused       : bool
            - message              : str — human-readable confirmation.

            Returns ``{"error": "..."}`` if the campaign is not found.
        """
        log.info(f"📞 [MARKETING] pause_marketing_campaign called | campaign_id={campaign_id}")
        async with get_session() as session:
            result = await session.execute(
                select(
                    MarketingCampaign.campaign_id,
                    MarketingCampaign.campaign_name,
                    MarketingCampaign.campaign_status,
                ).where(MarketingCampaign.campaign_id == campaign_id)
            )
            row = result.first()

            if row is None:
                return {"error": f"Campaign '{campaign_id}' not found."}

            previous = (
                row.campaign_status.value
                if hasattr(row.campaign_status, "value")
                else str(row.campaign_status)
            )
            already_paused = previous == "PAUSED"

            if not already_paused:
                await session.execute(
                    update(MarketingCampaign)
                    .where(MarketingCampaign.campaign_id == campaign_id)
                    .values(campaign_status=CampaignStatus.PAUSED)
                )

        non_active_warning = (
            f"  NOTE: campaign was already in '{previous}' state before pausing."
            if previous not in ("ACTIVE", "PAUSED")
            else ""
        )
        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": row.campaign_name,
            "previous_status": previous,
            "new_status": "PAUSED",
            "already_paused": already_paused,
            "message": (
                f"Campaign '{campaign_id}' ({row.campaign_name}) status set to PAUSED. "
                f"Ad spend halted immediately.{non_active_warning}"
                if not already_paused
                else f"Campaign '{campaign_id}' was already PAUSED. No change made."
            ),
        }

    @mcp.tool()
    async def adjust_campaign_budget(campaign_id: str, new_budget: float) -> dict:
        """Update the daily budget ceiling for a campaign.

        This write tool modifies the ``daily_budget`` column in
        ``marketing_campaigns`` for the specified campaign.  It is used to scale
        up high-performing acquisition channels during major sale events, or to
        reduce spend on underperforming campaigns without fully pausing them.

        This tool **must only be invoked from within the**
        ``execute_approved_actions`` **node** after explicit human approval.

        Budget change impact analysis
        ------------------------------
        The response includes a ``budget_change_analysis`` block to give the
        operator context on the adjustment:

        - ``change_direction``: ``INCREASE`` | ``DECREASE`` | ``UNCHANGED``
        - ``change_pct``      : float — percentage change from old to new budget.
        - ``current_spend``   : str — today's spend already committed (cannot be
                                recovered even if budget is lowered).
        - ``remaining_budget``: str — new_budget − total_spend_today.  Negative
                                values indicate the new cap is already exceeded.

        Validation
        ----------
        - ``new_budget`` must be > 0.
        - Lowering the budget below ``total_spend_today`` is allowed (to signal
          intent) but triggers a warning in the response.

        Parameters
        ----------
        campaign_id : str   — Campaign primary key (e.g., ``'CAMP-FB-911'``).
        new_budget  : float — New daily budget ceiling in USD.  Must be > 0.

        Returns
        -------
        dict
            Keys:
            - success                : bool
            - campaign_id            : str
            - campaign_name          : str
            - old_budget             : str
            - new_budget             : str
            - budget_change_analysis : dict — change_direction, change_pct,
                                       current_spend, remaining_budget.
            - message                : str — human-readable confirmation.

            Returns ``{"error": "..."}`` if the campaign is not found or
            ``new_budget`` is not a positive number.
        """
        log.info(f"📞 [MARKETING] adjust_campaign_budget called | campaign_id={campaign_id}, new_budget={new_budget}")
        if new_budget <= 0:
            return {"error": "new_budget must be a positive number greater than 0."}

        async with get_session() as session:
            result = await session.execute(
                select(
                    MarketingCampaign.campaign_id,
                    MarketingCampaign.campaign_name,
                    MarketingCampaign.daily_budget,
                    MarketingCampaign.total_spend_today,
                ).where(MarketingCampaign.campaign_id == campaign_id)
            )
            row = result.first()

            if row is None:
                return {"error": f"Campaign '{campaign_id}' not found."}

            old_budget = float(row.daily_budget)
            spend = float(row.total_spend_today)

            await session.execute(
                update(MarketingCampaign)
                .where(MarketingCampaign.campaign_id == campaign_id)
                .values(daily_budget=Decimal(str(round(new_budget, 2))))
            )

        if old_budget == new_budget:
            direction = "UNCHANGED"
            change_pct = 0.0
        elif new_budget > old_budget:
            direction = "INCREASE"
            change_pct = round(((new_budget - old_budget) / old_budget) * 100, 2)
        else:
            direction = "DECREASE"
            change_pct = round(((old_budget - new_budget) / old_budget) * 100, 2)

        remaining = new_budget - spend
        overspend_warning = (
            "  WARNING: new_budget is below today's committed spend — "
            "campaign may continue until the platform enforces the new cap."
            if remaining < 0
            else ""
        )

        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": row.campaign_name,
            "old_budget": f"{old_budget:.2f}",
            "new_budget": f"{new_budget:.2f}",
            "budget_change_analysis": {
                "change_direction": direction,
                "change_pct": change_pct,
                "current_spend": f"{spend:.2f}",
                "remaining_budget": f"{remaining:.2f}",
            },
            "message": (
                f"Daily budget for '{campaign_id}' ({row.campaign_name}) updated from "
                f"${old_budget:.2f} to ${new_budget:.2f} ({direction} of {change_pct}%).  "
                f"Remaining budget today: ${remaining:.2f}.{overspend_warning}"
            ),
        }

    @mcp.tool()
    async def update_campaign_status(campaign_id: str, new_status: str) -> dict:
        """Update campaign lifecycle state for an existing campaign.

        This is a generic status mutation tool for campaign operations. It can
        be used to activate, pause, complete, or mark a campaign budget
        exhausted based on approved operator actions.

        Parameters
        ----------
        campaign_id : str
            Campaign primary key (e.g., ``'CAMP-FB-902'``).
        new_status : str
            One of ``ACTIVE``, ``PAUSED``, ``COMPLETED``, ``BUDGET_EXHAUSTED``.

        Returns
        -------
        dict
            Mutation result with previous/new status and confirmation message.
        """
        log.info(
            "📞 [MARKETING] update_campaign_status called | campaign_id=%s, new_status=%s",
            campaign_id,
            new_status,
        )

        normalized = (new_status or "").strip().upper()
        try:
            status_enum = CampaignStatus(normalized)
        except ValueError:
            allowed = ", ".join(s.value for s in CampaignStatus)
            return {"error": f"Invalid new_status '{new_status}'. Allowed values: {allowed}."}

        async with get_session() as session:
            result = await session.execute(
                select(
                    MarketingCampaign.campaign_id,
                    MarketingCampaign.campaign_name,
                    MarketingCampaign.campaign_status,
                ).where(MarketingCampaign.campaign_id == campaign_id)
            )
            row = result.first()
            if row is None:
                return {"error": f"Campaign '{campaign_id}' not found."}

            previous = (
                row.campaign_status.value
                if hasattr(row.campaign_status, "value")
                else str(row.campaign_status)
            )
            already_same = previous == status_enum.value

            if not already_same:
                await session.execute(
                    update(MarketingCampaign)
                    .where(MarketingCampaign.campaign_id == campaign_id)
                    .values(campaign_status=status_enum)
                )

        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": row.campaign_name,
            "previous_status": previous,
            "new_status": status_enum.value,
            "already_in_status": already_same,
            "message": (
                f"Campaign '{campaign_id}' status updated from {previous} to {status_enum.value}."
                if not already_same
                else f"Campaign '{campaign_id}' is already in status {status_enum.value}."
            ),
        }

    @mcp.tool()
    async def create_marketing_campaign(
        product_name_or_id: str,
        campaign_name: str,
        channel: str,
        daily_budget: float,
        target_audience: str,
        tracking_utm_code: str = "",
    ) -> dict:
        """Create a new campaign with auto-resolved product id and generated campaign id.

        If ``product_name_or_id`` is already an exact product_id, it is used
        directly. Otherwise the tool performs a fuzzy match against product
        title/sku/brand and uses the unique match.

        Campaign ID is auto-generated using channel prefix format:
        ``CAMP-<PREFIX>-<NNN>`` (e.g., ``CAMP-FB-015``).

        Parameters
        ----------
        product_name_or_id : str
            Product identifier or human product name (e.g. "PROD-NK-001",
            "Nike Air Runner").
        campaign_name : str
            Human-readable campaign name.
        channel : str
            Channel name (Facebook_Ads, Google_Ads, TikTok_Ads, Email).
            Flexible inputs like "facebook" are accepted.
        daily_budget : float
            Daily budget in USD; must be > 0.
        target_audience : str
            Audience segment description.
        tracking_utm_code : str
            Optional UTM code.

        Returns
        -------
        dict
            Newly created campaign details.
        """
        log.info(
            "📞 [MARKETING] create_marketing_campaign called | product=%s, campaign_name=%s, channel=%s, daily_budget=%s",
            product_name_or_id,
            campaign_name,
            channel,
            daily_budget,
        )

        if daily_budget <= 0:
            return {"error": "daily_budget must be a positive number greater than 0."}
        if not campaign_name.strip():
            return {"error": "campaign_name cannot be empty."}
        if not target_audience.strip():
            return {"error": "target_audience cannot be empty."}

        normalized_channel = str(_normalize_channel(channel))
        try:
            channel_enum = MarketingChannel(normalized_channel)
        except Exception:
            allowed = "Facebook_Ads, Google_Ads, TikTok_Ads, Email"
            return {"error": f"Invalid channel '{channel}'. Allowed values: {allowed}."}

        async with get_session() as session:
            product_result = await session.execute(
                select(ProductInventory.product_id, ProductInventory.title, ProductInventory.sku, ProductInventory.brand)
                .where(ProductInventory.product_id == product_name_or_id)
            )
            exact = product_result.first()

            if exact is None:
                pattern = f"%{product_name_or_id}%"
                fuzzy_result = await session.execute(
                    select(
                        ProductInventory.product_id,
                        ProductInventory.title,
                        ProductInventory.sku,
                        ProductInventory.brand,
                    ).where(
                        or_(
                            ProductInventory.title.ilike(pattern),
                            ProductInventory.sku.ilike(pattern),
                            ProductInventory.brand.ilike(pattern),
                        )
                    ).order_by(ProductInventory.title.asc())
                )
                fuzzy_matches = fuzzy_result.all()

                if not fuzzy_matches:
                    return {
                        "error": (
                            f"No product found for '{product_name_or_id}'. "
                            "Resolve the product first using resolve_campaign_identifiers semantics."
                        )
                    }
                if len(fuzzy_matches) > 1:
                    return {
                        "error": (
                            f"Multiple products matched '{product_name_or_id}'. "
                            "Please provide a more specific product name or an exact product_id."
                        ),
                        "match_count": len(fuzzy_matches),
                        "matches": [
                            {
                                "product_id": r.product_id,
                                "title": r.title,
                                "sku": r.sku,
                                "brand": r.brand,
                            }
                            for r in fuzzy_matches[:10]
                        ],
                    }
                chosen = fuzzy_matches[0]
            else:
                chosen = exact

            prefix = _campaign_prefix(channel_enum.value)
            max_num_result = await session.execute(
                select(func.max(MarketingCampaign.campaign_id)).where(
                    MarketingCampaign.campaign_id.like(f"CAMP-{prefix}-%")
                )
            )
            latest_id = max_num_result.scalar_one_or_none()
            next_num = 1
            if latest_id:
                try:
                    next_num = int(str(latest_id).split("-")[-1]) + 1
                except Exception:
                    next_num = 1

            campaign_id = f"CAMP-{prefix}-{next_num:03d}"
            existing_id_check = await session.execute(
                select(MarketingCampaign.campaign_id).where(MarketingCampaign.campaign_id == campaign_id)
            )
            while existing_id_check.first() is not None:
                next_num += 1
                campaign_id = f"CAMP-{prefix}-{next_num:03d}"
                existing_id_check = await session.execute(
                    select(MarketingCampaign.campaign_id).where(MarketingCampaign.campaign_id == campaign_id)
                )

            now = datetime.utcnow()
            new_campaign = MarketingCampaign(
                campaign_id=campaign_id,
                campaign_name=campaign_name.strip(),
                channel=channel_enum,
                target_product_id=chosen.product_id,
                target_audience=target_audience.strip(),
                daily_budget=Decimal(str(round(daily_budget, 2))),
                total_spend_today=Decimal("0.00"),
                impressions=0,
                clicks=0,
                ctr=Decimal("0.00"),
                cpc=Decimal("0.00"),
                attributed_revenue=Decimal("0.00"),
                campaign_status=CampaignStatus.ACTIVE,
                tracking_utm_code=(tracking_utm_code.strip() or None),
                hourly_spend_log=[],
                created_at=now,
                updated_at=now,
            )
            session.add(new_campaign)

        return {
            "success": True,
            "campaign_id": campaign_id,
            "campaign_name": campaign_name.strip(),
            "product_id": chosen.product_id,
            "channel": channel_enum.value,
            "daily_budget": f"{float(daily_budget):.2f}",
            "campaign_status": "ACTIVE",
            "target_audience": target_audience.strip(),
            "tracking_utm_code": tracking_utm_code.strip() or None,
            "message": (
                f"Created campaign '{campaign_id}' for product '{chosen.product_id}' "
                f"with daily budget ${float(daily_budget):.2f}."
            ),
        }
