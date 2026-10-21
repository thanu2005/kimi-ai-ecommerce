"""customer_support_tickets — customer complaint and resolution tracking ledger."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Numeric, Text
from sqlmodel import Field, Relationship, SQLModel

from app.db.models.catalog import ProductInventory  # FK target


# --------------------------------------------------------------------------- #
#  Enums                                                                       #
# --------------------------------------------------------------------------- #

class TicketCategory(str, Enum):
    """Issue classification assigned at ticket creation or triage."""
    CHECKOUT_ERROR = "Checkout_Error"
    SHIPPING_DELAY = "Shipping_Delay"
    PRODUCT_DEFECT = "Product_Defect"
    REFUND_REQUEST = "Refund_Request"


class TicketPriority(str, Enum):
    """Urgency tier used to route tickets through the support queue."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TicketStatus(str, Enum):
    """Current queue lifecycle state of the ticket."""
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ResolutionType(str, Enum):
    """Operational action taken to close the ticket."""
    ISSUED_REFUND = "ISSUED_REFUND"
    REPLACEMENT_SENT = "REPLACEMENT_SENT"
    COUPON_FIXED = "COUPON_FIXED"
    STORE_CREDIT = "STORE_CREDIT"


# --------------------------------------------------------------------------- #
#  Table model                                                                 #
# --------------------------------------------------------------------------- #

class CustomerSupportTicket(SQLModel, table=True):
    """Maps to the `customer_support_tickets` PostgreSQL table.

    Each row represents a single customer complaint or query.  Resolution
    actions and status transitions are executed exclusively through MCP
    server tools — never directly from agent nodes.
    """

    __tablename__ = "customer_support_tickets"

    # ------------------------------------------------------------------ #
    #  Identity / Keys                                                     #
    # ------------------------------------------------------------------ #
    ticket_id: str = Field(
        primary_key=True,
        max_length=50,
        description="Unique ticket identifier (e.g. TKT-88301).",
    )
    customer_id: str = Field(
        max_length=50,
        index=True,
        description="Unique user footprint identifier that opened this complaint.",
    )
    order_id: Optional[str] = Field(
        default=None,
        max_length=50,
        index=True,
        description="FK → order_items.order_id; NULL for generic browsing or account issues.",
    )
    product_id: Optional[str] = Field(
        default=None,
        max_length=50,
        foreign_key="products_inventory.product_id",
        index=True,
        description="FK → products_inventory.product_id; NULL when not item-specific.",
    )

    # ------------------------------------------------------------------ #
    #  Ticket Content                                                      #
    # ------------------------------------------------------------------ #
    subject: str = Field(
        max_length=255,
        description="Short summary line entered by the customer (e.g. Promo code invalid).",
    )
    customer_text: str = Field(
        sa_column=Column(Text, nullable=False),
        description="Full raw text body containing the customer's verbatim complaint.",
    )

    # ------------------------------------------------------------------ #
    #  Classification & Priority                                           #
    # ------------------------------------------------------------------ #
    ticket_category: TicketCategory = Field(
        description="Issue type: Checkout_Error | Shipping_Delay | Product_Defect | Refund_Request.",
    )
    priority: TicketPriority = Field(
        default=TicketPriority.MEDIUM,
        description="Urgency tier: LOW | MEDIUM | HIGH | CRITICAL.",
    )
    ticket_status: TicketStatus = Field(
        default=TicketStatus.OPEN,
        description="Queue lifecycle state: OPEN | IN_PROGRESS | RESOLVED | ESCALATED.",
    )

    # ------------------------------------------------------------------ #
    #  Sentiment & Assignment                                              #
    # ------------------------------------------------------------------ #
    sentiment_score: Decimal = Field(
        sa_column=Column(Numeric(3, 2), nullable=False),
        description=(
            "Sentiment polarity score (NUMERIC 3,2): "
            "-1.0 = furious, 0.0 = neutral, 1.0 = happy. "
            "Populated by the support agent's NLP analysis tool."
        ),
    )
    assigned_agent_id: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Human support specialist currently owning this ticket; NULL if unassigned.",
    )

    # ------------------------------------------------------------------ #
    #  Resolution                                                          #
    # ------------------------------------------------------------------ #
    resolution_type: Optional[ResolutionType] = Field(
        default=None,
        description="Action taken to close the ticket: ISSUED_REFUND | REPLACEMENT_SENT | COUPON_FIXED | STORE_CREDIT; NULL while open.",
    )

    # ------------------------------------------------------------------ #
    #  Timestamps                                                          #
    # ------------------------------------------------------------------ #
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of when the ticket was opened by the customer.",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the last agent update or status change.",
    )
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of when the ticket was moved to a finalised state; NULL while active.",
    )

    # ------------------------------------------------------------------ #
    #  Relationships                                                       #
    # ------------------------------------------------------------------ #
    product: Optional[ProductInventory] = Relationship()
