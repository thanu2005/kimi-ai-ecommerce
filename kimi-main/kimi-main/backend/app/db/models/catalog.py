"""products_inventory — master product catalog and real-time inventory ledger."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Numeric
from sqlmodel import Field, SQLModel


# --------------------------------------------------------------------------- #
#  Enums                                                                       #
# --------------------------------------------------------------------------- #

class RestockStatus(str, Enum):
    """Allowed replenishment states for a product SKU.

    Using `str` as the mixin means Pydantic serialises the value as a plain
    string (not an object), and PostgreSQL stores a VARCHAR — no DB enum type
    migration required.
    """

    NORMAL = "NORMAL"
    BELOW_SAFETY = "BELOW_SAFETY"
    PO_PLACED = "PO_PLACED"
    BACKORDERED = "BACKORDERED"


# --------------------------------------------------------------------------- #
#  Table model                                                                 #
# --------------------------------------------------------------------------- #

class ProductInventory(SQLModel, table=True):
    """Maps to the `products_inventory` PostgreSQL table.

    Every row represents a single active or archived SKU.  Inventory
    counters (physical_stock, allocated_stock) are updated exclusively
    through MCP server tools — never directly from agent nodes.
    """

    __tablename__ = "products_inventory"

    # ------------------------------------------------------------------ #
    #  Identity                                                            #
    # ------------------------------------------------------------------ #
    product_id: str = Field(
        primary_key=True,
        max_length=50,
        description="Unique alphanumeric product identifier (e.g. PROD-LJ-001).",
    )
    sku: str = Field(
        max_length=50,
        index=True,
        description="Stock Keeping Unit used for warehouse tracking (e.g. APP-LEA-JKT-BLK-XL).",
    )

    # ------------------------------------------------------------------ #
    #  Display Metadata                                                    #
    # ------------------------------------------------------------------ #
    title: str = Field(
        max_length=255,
        description="Front-end display name of the product.",
    )
    brand: str = Field(
        max_length=100,
        description="Manufacturer or house brand name (e.g. Nike, Sony).",
    )
    category: str = Field(
        max_length=100,
        index=True,
        description="High-level product vertical (e.g. Apparel, Electronics, Home).",
    )
    sub_category: str = Field(
        max_length=100,
        index=True,
        description="Granular classification beneath category (e.g. Outerwear, Smartphones).",
    )

    # ------------------------------------------------------------------ #
    #  Pricing  — Decimal maps to PostgreSQL NUMERIC for exact arithmetic  #
    # ------------------------------------------------------------------ #
    cost_price: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Wholesale cost paid to the supplier (NUMERIC 10,2).",
    )
    retail_price: Decimal = Field(
        sa_column=Column(Numeric(10, 2), nullable=False),
        description="Current active selling price displayed on the website (NUMERIC 10,2).",
    )
    compare_at_price: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(10, 2), nullable=True),
        description="Original MSRP before any markdown; NULL when not on sale (NUMERIC 10,2).",
    )

    # ------------------------------------------------------------------ #
    #  Inventory Counters                                                  #
    # ------------------------------------------------------------------ #
    physical_stock: int = Field(
        ge=0,
        description="Actual unit count physically present on warehouse shelves.",
    )
    allocated_stock: int = Field(
        default=0,
        ge=0,
        description="Units sold but not yet packed or shipped. Available = physical_stock - allocated_stock.",
    )
    safety_stock_level: int = Field(
        ge=0,
        description="Minimum stock buffer before a reorder is triggered.",
    )
    reorder_quantity: int = Field(
        ge=1,
        description="Default batch size sent to the supplier on each restock purchase order.",
    )

    # ------------------------------------------------------------------ #
    #  Restock / Supplier                                                  #
    # ------------------------------------------------------------------ #
    restock_status: RestockStatus = Field(
        default=RestockStatus.NORMAL,
        description="Replenishment state — validated by Pydantic to one of: NORMAL | BELOW_SAFETY | PO_PLACED | BACKORDERED.",
    )
    supplier_id: str = Field(
        max_length=50,
        index=True,
        description="Primary vendor code linked to this SKU.",
    )
    supplier_lead_time: int = Field(
        ge=0,
        description="Days required for the vendor to deliver a new stock batch.",
    )

    # ------------------------------------------------------------------ #
    #  Logistics / Dimensions                                              #
    # ------------------------------------------------------------------ #
    weight_kg: Decimal = Field(
        sa_column=Column(Numeric(6, 2), nullable=False),
        description="Gross item weight in kilograms used for shipping tier calculations (NUMERIC 6,2).",
    )
    length_cm: int = Field(
        ge=0,
        description="Item length in centimetres for volumetric weight calculations.",
    )
    width_cm: int = Field(
        ge=0,
        description="Item width in centimetres for volumetric weight calculations.",
    )
    height_cm: int = Field(
        ge=0,
        description="Item height in centimetres for volumetric weight calculations.",
    )
    warehouse_location: str = Field(
        max_length=50,
        description="Bin location code on the warehouse floor (e.g. Aisle-04-Shelf-C-Bin-12).",
    )

    # ------------------------------------------------------------------ #
    #  Visibility / Timestamps                                             #
    # ------------------------------------------------------------------ #
    is_active: bool = Field(
        default=True,
        description="Hard toggle; False removes the product page from consumer view.",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of when this product record was first created.",
    )
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="UTC timestamp of the last inventory audit or metadata update.",
    )
