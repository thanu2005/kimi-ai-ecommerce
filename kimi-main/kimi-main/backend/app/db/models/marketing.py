"""marketing_campaigns — ad channel performance and spend tracking ledger."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Column, JSON, Numeric
from sqlmodel import Field, Relationship, SQLModel

from app.db.models.catalog import ProductInventory  # FK target


# --------------------------------------------------------------------------- #
#  Enums                                                                       #
# --------------------------------------------------------------------------- #

class MarketingChannel(str, Enum):
    """Allowed ad network source channels."""
    FACEBOOK_ADS = "Facebook_Ads"
    GOOGLE_ADS = "Google_Ads"
    TIKTOK_ADS = "TikTok_Ads"
    EMAIL = "Email"


class CampaignStatus(str, Enum):
    """Platform-reported lifecycle state of the campaign."""
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


# --------------------------------------------------------------------------- #
#  Table model                                                                 #
# --------------------------------------------------------------------------- #

class MarketingCampaign(SQLModel, table=True):
    """Maps to the `marketing_campaigns` PostgreSQL table.

    Each row tracks a single ad campaign's spend, engagement metrics, and
    platform status.  Mutations (pausing, budget adjustments) are performed
    exclusively through MCP server tools — never directly from agent nodes.
    """

    __tablename__ = "marketing_campaigns"

    # ------------------------------------------------------------------ #
    #  Identity / Keys                                                     #
    # ------------------------------------------------------------------ #
    campaign_id: str = Field(
        primary_key=True,
        max_length=50,
        description="Unique ad campaign identifier (e.g. CAMP-FB-902).",
    )
    campaign_name: str = Field(
        max_length=255,
        description="Human-readable campaign label (e.g. IG_Influencer_LeatherJacket).",
    )
    channel: MarketingChannel = Field(
        description="Source ad network: Facebook_Ads | Google_Ads | TikTok_Ads | Email.",
    )
    target_product_id: str = Field(
        max_length=50,
        foreign_key="products_inventory.product_id",
        index=True,
        description="FK → products_inventory.product_id — the SKU this campaign is promoting.",
    )
    target_audience: str = Field(
        max_length=100,
        description="Audience profile targeted by this campaign (e.g. Retargeting_Cart_Abandoners).",
    )

    # ------------------------------------------------------------------ #
    #  Budget & Spend                                                      #
    # ------------------------------------------------------------------ #
    daily_budget: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Maximum dollar spend cap for this campaign per calendar day (NUMERIC 10,2).",
    )
    total_spend_today: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Budget burned since 00:00 AM today (NUMERIC 10,2).",
    )

    # ------------------------------------------------------------------ #
    #  Engagement Metrics                                                  #
    # ------------------------------------------------------------------ #
    impressions: int = Field(
        default=0,
        ge=0,
        description="Total ad views registered on user screens.",
    )
    clicks: int = Field(
        default=0,
        ge=0,
        description="Total click-through events leading to the storefront.",
    )
    ctr: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(5, 2), nullable=False),
        description="Click-Through Rate: (clicks / impressions) * 100 (NUMERIC 5,2).",
    )
    cpc: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Cost Per Click: total_spend_today / clicks (NUMERIC 10,2).",
    )
    attributed_revenue: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Revenue attributed by the platform pixel tracking system (NUMERIC 10,2).",
    )

    # ------------------------------------------------------------------ #
    #  Status & Tracking                                                   #
    # ------------------------------------------------------------------ #
    campaign_status: CampaignStatus = Field(
        default=CampaignStatus.ACTIVE,
        description="Platform lifecycle state: ACTIVE | PAUSED | COMPLETED | BUDGET_EXHAUSTED.",
    )
    tracking_utm_code: Optional[str] = Field(
        default=None,
        max_length=100,
        description="URL UTM parameters for traffic attribution (e.g. utm_campaign=jacket_blast).",
    )

    # ------------------------------------------------------------------ #
    #  Hourly Spend Log  (JSONB)                                           #
    # ------------------------------------------------------------------ #
    hourly_spend_log: Optional[list[Any]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description=(
            "JSONB array mapping hourly cost allocations. "
            'Schema: [{"hour": 0, "spend": 12.50}, {"hour": 1, "spend": 14.10}, ...]. '
            "Populated by the campaign metrics sync tool; NULL until first data arrives."
        ),
    )

    # ------------------------------------------------------------------ #
    #  Timestamps                                                          #
    # ------------------------------------------------------------------ #
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of campaign launch.",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the last manual optimization or platform sync.",
    )

    # ------------------------------------------------------------------ #
    #  Relationships                                                       #
    # ------------------------------------------------------------------ #
    product: Optional[ProductInventory] = Relationship()
