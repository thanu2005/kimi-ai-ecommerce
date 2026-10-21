"""order_items — individual transaction line items linked to the product catalog."""

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Date, Numeric
from sqlmodel import Field, Relationship, SQLModel

from app.db.models.catalog import ProductInventory  # FK target


# --------------------------------------------------------------------------- #
#  Enums                                                                       #
# --------------------------------------------------------------------------- #

class PaymentGateway(str, Enum):
    """Allowed payment processor routes."""
    STRIPE = "Stripe"
    PAYPAL = "PayPal"
    RAZORPAY = "Razorpay"


class PaymentStatus(str, Enum):
    """Processor-reported settlement state."""
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"
    CHARGEBACK = "CHARGEBACK"


class OrderStatus(str, Enum):
    """Fulfillment lifecycle stage."""
    UNFULFILLED = "UNFULFILLED"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class CheckoutDevice(str, Enum):
    """Consumer hardware channel used at checkout."""
    MOBILE_APP = "Mobile_App"
    MOBILE_WEB = "Mobile_Web"
    DESKTOP = "Desktop"


# --------------------------------------------------------------------------- #
#  Table model                                                                 #
# --------------------------------------------------------------------------- #

class OrderItem(SQLModel, table=True):
    """Maps to the `order_items` PostgreSQL table.

    Each row is one product line within a customer transaction.  Multiple
    rows may share the same `order_id` when a cart contains several SKUs.
    Write-mutations (status updates, refund flags) are performed exclusively
    through MCP server tools.
    """

    __tablename__ = "order_items"

    # ------------------------------------------------------------------ #
    #  Identity / Keys                                                     #
    # ------------------------------------------------------------------ #
    line_item_id: str = Field(
        primary_key=True,
        max_length=50,
        description="Unique identifier for this transaction line row (e.g. LINE-55301).",
    )
    order_id: str = Field(
        max_length=50,
        index=True,
        description="Overarching transaction ID; multiple line items may share this value.",
    )
    customer_id: str = Field(
        max_length=50,
        index=True,
        description="Unique customer profile identifier.",
    )
    product_id: str = Field(
        max_length=50,
        foreign_key="products_inventory.product_id",
        index=True,
        description="FK → products_inventory.product_id.",
    )

    # ------------------------------------------------------------------ #
    #  Quantity & Pricing                                                  #
    # ------------------------------------------------------------------ #
    quantity: int = Field(
        ge=1,
        description="Units purchased for this product line.",
    )
    unit_retail_price: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Baseline item price at the exact moment of user checkout (NUMERIC 10,2).",
    )
    discount_applied: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Total value subtracted from this line via markdowns or promo codes (NUMERIC 10,2).",
    )
    gross_revenue: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Final line value: (quantity * unit_retail_price) - discount_applied (NUMERIC 10,2).",
    )

    # ------------------------------------------------------------------ #
    #  Payment                                                             #
    # ------------------------------------------------------------------ #
    payment_gateway: PaymentGateway = Field(
        description="Processor used for transaction routing: Stripe | PayPal | Razorpay.",
    )
    payment_status: PaymentStatus = Field(
        description="Processor settlement state: SUCCESS | FAILED | REFUNDED | CHARGEBACK.",
    )

    # ------------------------------------------------------------------ #
    #  Shipping                                                            #
    # ------------------------------------------------------------------ #
    shipping_country: str = Field(
        max_length=100,
        index=True,
        description="Destination country for delivery.",
    )
    shipping_state: str = Field(
        max_length=100,
        description="Granular destination zone (e.g. Texas, Telangana, California).",
    )
    shipping_cost: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Total shipping fee charged to the customer (NUMERIC 10,2).",
    )

    # ------------------------------------------------------------------ #
    #  Fulfillment                                                         #
    # ------------------------------------------------------------------ #
    order_status: OrderStatus = Field(
        default=OrderStatus.UNFULFILLED,
        description="Fulfillment lifecycle stage: UNFULFILLED | PROCESSING | SHIPPED | DELIVERED.",
    )
    checkout_device: CheckoutDevice = Field(
        description="Frontend channel used at checkout: Mobile_App | Mobile_Web | Desktop.",
    )
    estimated_delivery: date = Field(
        sa_column=Column(Date, nullable=False),
        description="Promised arrival date generated by logistics parameters at checkout.",
    )
    actual_delivery: Optional[date] = Field(
        default=None,
        sa_column=Column(Date, nullable=True),
        description="Confirmed delivery date from the carrier; NULL while shipment is in transit.",
    )

    # ------------------------------------------------------------------ #
    #  Promo / Audit                                                       #
    # ------------------------------------------------------------------ #
    promo_code_used: Optional[str] = Field(
        default=None,
        max_length=50,
        description="Exact voucher string entered at checkout (e.g. SUMMER20); NULL if none.",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of when the order transaction was completed.",
    )

    # ------------------------------------------------------------------ #
    #  Relationships                                                       #
    # ------------------------------------------------------------------ #
    product: Optional[ProductInventory] = Relationship()
