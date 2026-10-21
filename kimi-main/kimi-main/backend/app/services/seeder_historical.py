"""Historical bulk seeder — 2025-01-01 to 2026-06-05.

Generates approximately:
  • 30,000+ order lines across 15 products
  • 160  marketing campaigns  (8–10 per month, all 4 channels)
  • 1,050 support tickets causally linked to orders

Seasonal patterns baked in:
  • Jan       — New-Year fitness boom (yoga mat, resistance bands +60%)
  • Feb       — Valentine spike (perfume, scarves +50%)
  • May–Jul   — Summer peak (sunglasses, running shoes +50%)
  • Sep       — Back-to-school (electronics +10%)
  • Nov BF    — Black Friday week ×2.8 volume
  • Dec 2     — Cyber Monday ×2.5 volume
  • Dec 20–25 — Christmas week ×1.9 volume
  • Nov–Dec   — Holiday gift peak (headphones, smart-watch, gaming chair +50%)

Usage
-----
    uv run python -m app.services.seeder_historical
"""

import asyncio
from datetime import date, datetime, timedelta
from decimal import Decimal
from random import Random

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db.models.marketing import CampaignStatus, MarketingCampaign, MarketingChannel
from app.db.models.sales import (
    CheckoutDevice,
    OrderItem,
    OrderStatus,
    PaymentGateway,
    PaymentStatus,
)
from app.db.models.support import (
    CustomerSupportTicket,
    ResolutionType,
    TicketCategory,
    TicketPriority,
    TicketStatus,
)
from app.db.session import AsyncSessionLocal, create_db_and_tables

RNG = Random(20250101)  # fixed seed → reproducible runs

# ── Date range ────────────────────────────────────────────────────────────────

START = date(2025, 1, 1)
END   = date(2026, 6, 5)   # June 6 2026 already seeded by seeder.py

# ── Product catalogue ─────────────────────────────────────────────────────────
# (product_id, retail_price, promo_codes)

PRODUCTS: list[tuple[str, Decimal, list[str]]] = [
    ("PROD-LJ-001", Decimal("129.99"), ["SUMMER20", "FALL15", "WINTER25"]),
    ("PROD-WH-002", Decimal("89.99"),  ["AUDIO10", "TECH15"]),
    ("PROD-RS-003", Decimal("109.99"), ["RUN20", "FITNESS15"]),
    ("PROD-SP-004", Decimal("24.99"),  ["CASE10"]),
    ("PROD-YM-005", Decimal("39.99"),  ["WELLNESS15", "FIT10"]),
    ("PROD-SW-006", Decimal("249.99"), ["LAUNCH50", "TECH20"]),
    ("PROD-DB-007", Decimal("74.99"),  ["DENIM10", "STYLE15"]),
    ("PROD-BT-008", Decimal("59.99"),  ["BASS20", "AUDIO15"]),
    ("PROD-SC-009", Decimal("49.99"),  ["LUXE10"]),
    ("PROD-GC-010", Decimal("299.99"), ["GAME20", "GAMING15"]),
    ("PROD-CM-011", Decimal("79.99"),  ["KITCHEN20", "HOME15"]),
    ("PROD-PS-012", Decimal("69.99"),  ["GIFT10", "SCENT15"]),
    ("PROD-LS-013", Decimal("44.99"),  ["WFH10", "DESK15"]),
    ("PROD-RB-014", Decimal("24.99"),  ["FIT5", "FITNESS10"]),
    ("PROD-SG-015", Decimal("34.99"),  ["SUMMER10", "SHADE15"]),
]

PROD_TITLES: dict[str, str] = {
    "PROD-LJ-001": "Classic Black Leather Jacket",
    "PROD-WH-002": "ProSound Wireless Headphones",
    "PROD-RS-003": "Nike Air Zoom Runner",
    "PROD-SP-004": "MagGuard iPhone 16 Pro Case",
    "PROD-YM-005": "FlexCore Premium Yoga Mat",
    "PROD-SW-006": "NexWatch Series X Smart Watch",
    "PROD-DB-007": "Urban Fade Denim Jacket",
    "PROD-BT-008": "BassBox Pro Bluetooth Speaker",
    "PROD-SC-009": "Silk Bloom Designer Scarf",
    "PROD-GC-010": "ErgoZone Pro Gaming Chair",
    "PROD-CM-011": "BrewMaster 12-Cup Coffee Maker",
    "PROD-PS-012": "Bloom Elegance Perfume Gift Set",
    "PROD-LS-013": "AluRise Adjustable Laptop Stand",
    "PROD-RB-014": "FlexForce Resistance Bands Set",
    "PROD-SG-015": "ShadeLux Polarised Sunglasses",
}

# Monthly seasonal multiplier per product  [index 0 = Jan … 11 = Dec]
SEASONAL: dict[str, list[float]] = {
    "PROD-LJ-001": [0.80, 0.70, 0.50, 0.40, 0.30, 0.30, 0.20, 0.30, 0.50, 0.80, 1.20, 1.50],
    "PROD-WH-002": [0.80, 0.80, 0.80, 0.80, 0.90, 0.90, 0.90, 1.00, 1.10, 1.00, 1.30, 1.50],
    "PROD-RS-003": [0.90, 0.80, 1.10, 1.30, 1.40, 1.20, 1.10, 1.20, 1.10, 0.90, 0.70, 0.60],
    "PROD-SP-004": [1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.10, 1.00, 1.20, 1.40],
    "PROD-YM-005": [1.60, 1.40, 1.20, 1.00, 0.90, 0.90, 0.90, 1.00, 1.00, 0.90, 0.80, 0.70],
    "PROD-SW-006": [0.90, 0.80, 0.80, 0.90, 0.90, 0.90, 0.80, 0.90, 1.00, 1.00, 1.30, 1.50],
    "PROD-DB-007": [0.70, 0.70, 0.90, 1.10, 1.20, 1.00, 1.00, 1.10, 1.20, 1.20, 1.00, 0.80],
    "PROD-BT-008": [0.90, 0.90, 0.90, 0.90, 1.00, 1.00, 1.10, 1.00, 1.00, 1.00, 1.20, 1.40],
    "PROD-SC-009": [0.80, 1.30, 0.90, 0.90, 0.80, 0.80, 0.80, 0.80, 0.90, 1.00, 1.10, 1.30],
    "PROD-GC-010": [1.00, 1.00, 1.00, 0.90, 0.90, 0.90, 1.00, 1.00, 1.00, 1.10, 1.30, 1.50],
    "PROD-CM-011": [1.00, 1.00, 0.90, 0.90, 0.90, 0.90, 0.90, 0.90, 1.00, 1.00, 1.20, 1.40],
    "PROD-PS-012": [1.00, 1.50, 1.00, 0.90, 0.90, 0.90, 0.80, 0.90, 0.90, 1.00, 1.10, 1.40],
    "PROD-LS-013": [1.10, 1.10, 1.00, 1.00, 1.00, 1.00, 0.90, 1.00, 1.10, 1.00, 1.10, 1.00],
    "PROD-RB-014": [1.60, 1.40, 1.10, 1.00, 1.00, 0.90, 0.90, 1.00, 1.00, 0.90, 0.80, 0.70],
    "PROD-SG-015": [0.40, 0.50, 0.70, 1.00, 1.30, 1.50, 1.50, 1.20, 0.80, 0.60, 0.40, 0.30],
}

# Base probability weight per product (sums to 1.0 before seasonal adjustment)
BASE_WEIGHTS = [0.06, 0.09, 0.08, 0.10, 0.07, 0.05, 0.08, 0.07, 0.06,
                0.05, 0.07, 0.06, 0.07, 0.07, 0.06]

# Daily base order volume by month  [0 = Jan … 11 = Dec]
VOLUME_2025 = [45, 48, 52, 55, 58, 60, 56, 59, 63, 66, 95, 118]
VOLUME_2026 = [int(v * 1.18) for v in VOLUME_2025]  # 18% YoY growth

SHIPPING_LOCATIONS: list[tuple[str, str]] = [
    ("United States", "California"),  ("United States", "Texas"),
    ("United States", "New York"),    ("United States", "Florida"),
    ("United States", "Illinois"),    ("United States", "Washington"),
    ("United States", "Colorado"),    ("United States", "Oregon"),
    ("United States", "Arizona"),     ("United States", "Nevada"),
    ("United States", "Michigan"),    ("United States", "Georgia"),
    ("United Kingdom", "England"),    ("United Kingdom", "Scotland"),
    ("India", "Maharashtra"),         ("India", "Telangana"),
    ("India", "Karnataka"),           ("India", "Delhi"),
    ("Germany", "Bavaria"),           ("Germany", "Berlin"),
    ("Canada", "Ontario"),            ("Canada", "British Columbia"),
    ("Australia", "New South Wales"), ("France", "Ile-de-France"),
    ("United Arab Emirates", "Dubai"),("Singapore", "Central Region"),
]

AUDIENCES: list[str] = [
    "Retargeting_Cart_Abandoners",   "Lookalike_Past_Buyers",
    "Interest_Based_Shoppers",       "In_Market_Buyers",
    "Brand_Intent_Keywords",         "Subscribed_Buyers",
    "GenZ_Lifestyle_Audience",       "Remote_Workers_25_45",
    "Fitness_Enthusiasts_18_34",     "Gift_Buyers_Seasonal",
    "Tech_Early_Adopters_25_45",     "Fashion_Shoppers_Broad_Match",
    "Wellness_Newsletter_Subscribers","Gaming_Community_18_30",
    "Home_Appliance_Buyers",
]

DEFECTS: list[str] = [
    "screen stopped responding within the first hour",
    "stitching came apart on first wear",
    "charging port does not connect properly",
    "clasp broke during first use",
    "material developed holes after one wash",
    "battery drains fully within 2 hours",
    "buckle snapped without warning",
    "lens cracked without any physical impact",
    "zipper is stuck and will not open",
    "adhesive on the back is already peeling",
    "knobs are loose and wobble significantly",
    "colour faded significantly after the first wash",
]

CH_CODE: dict[MarketingChannel, str] = {
    MarketingChannel.FACEBOOK_ADS: "FB",
    MarketingChannel.GOOGLE_ADS:   "GG",
    MarketingChannel.TIKTOK_ADS:   "TT",
    MarketingChannel.EMAIL:        "EM",
}

TICKET_TEMPLATES: list[tuple[TicketCategory, str, str]] = [
    (
        TicketCategory.SHIPPING_DELAY,
        "Order {order_id} not arrived — expected {est_date}",
        (
            "I placed an order for {title} ({order_id}) on {order_date} with an estimated "
            "delivery of {est_date}, but the item has still not arrived. The tracking has "
            "not updated in over 3 days. Please investigate and provide an updated delivery "
            "estimate or arrange redelivery at the earliest opportunity."
        ),
    ),
    (
        TicketCategory.PRODUCT_DEFECT,
        "Defective item received — {title}",
        (
            "I received my {title} ({order_id}) today but found a defect: the {defect}. "
            "I tested it immediately after unboxing and the problem was present from the "
            "start. This is clearly a manufacturing defect. Please arrange a full replacement "
            "or process a refund."
        ),
    ),
    (
        TicketCategory.REFUND_REQUEST,
        "Refund request for {order_id} — item not as described",
        (
            "The {title} I received ({order_id}) does not match the product listing. The "
            "specification I received differs from what I selected at checkout. I would like "
            "a full refund to my original payment method and will return the item."
        ),
    ),
    (
        TicketCategory.CHECKOUT_ERROR,
        "Discount code not applying — {title}",
        (
            "I am trying to purchase {title} but my discount code is being rejected at the "
            "payment step with the message 'Code not valid for this item'. The code was sent "
            "in a promotional email this week. Please fix the issue or apply the discount "
            "manually to my account."
        ),
    ),
    (
        TicketCategory.PRODUCT_DEFECT,
        "Wrong item in package — ordered {title}",
        (
            "I ordered {title} ({order_id}) but the package I received contains a completely "
            "different product. The outer label matches my order but the contents are wrong. "
            "This appears to be a picking error at the warehouse. Please arrange collection "
            "and send the correct item."
        ),
    ),
    (
        TicketCategory.SHIPPING_DELAY,
        "Package returned to sender — {order_id}",
        (
            "The tracking for my {title} order ({order_id}) shows it was returned to the "
            "sender after a failed delivery attempt. I was available and received no "
            "notification or card. Please rebook the delivery or process a full refund."
        ),
    ),
    (
        TicketCategory.REFUND_REQUEST,
        "Item does not fit — requesting return for {title}",
        (
            "The {title} I received ({order_id}) does not fit correctly despite following "
            "the size guide on your website. I would like to arrange a free return and "
            "receive a full refund or store credit."
        ),
    ),
    (
        TicketCategory.PRODUCT_DEFECT,
        "Quality issue — {title} broken after first use",
        (
            "My {title} ({order_id}) broke after its very first use — the {defect}. I am "
            "extremely disappointed with the quality. I expect a full refund and recommend "
            "a quality review of this product line."
        ),
    ),
]

# ── Volume helpers ─────────────────────────────────────────────────────────────

def _daily_volume(d: date) -> int:
    vol_table = VOLUME_2025 if d.year == 2025 else VOLUME_2026
    base = vol_table[d.month - 1]
    mult = 0.90 if d.weekday() >= 5 else 1.0  # weekend dip ~10%

    # Calendar events
    if d.month == 11 and d.day >= 27:                    mult *= 2.80  # Black Friday week
    elif d.month == 12 and d.day == 2 and d.weekday() == 0:
        mult *= 2.50  # Cyber Monday
    elif d.month == 12 and 20 <= d.day <= 25:            mult *= 1.90  # Christmas week
    elif d.month == 1  and d.day <= 14:                  mult *= 1.30  # New Year resolutions
    elif d.month == 2  and 10 <= d.day <= 14:            mult *= 1.35  # Valentine's week

    count = int(base * mult)
    count += RNG.randint(-int(count * 0.12), int(count * 0.12))
    return max(8, count)


def _product_weights(d: date) -> list[float]:
    mi = d.month - 1
    return [BASE_WEIGHTS[i] * SEASONAL[pid][mi] for i, (pid, _, _) in enumerate(PRODUCTS)]


def _hour() -> int:
    return RNG.choices(
        list(range(24)),
        weights=[1, 1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 8, 7, 7, 8, 8, 7, 6, 5, 4, 4, 3, 2, 2],
    )[0]


# ── Row factories ──────────────────────────────────────────────────────────────

def _make_order(d: date, seq: int, prod_id: str, price: Decimal, promos: list[str]) -> dict:
    line_id  = f"LINE-{d.strftime('%Y%m%d')}-{seq:04d}"
    order_id = f"ORD-{d.strftime('%Y%m%d')}-{seq:04d}"
    cust_id  = f"CUST-{RNG.randint(1, 20000):06d}"

    promo    = RNG.choice(promos) if (promos and RNG.random() < 0.22) else None
    discount = Decimal("0.00")
    if promo:
        pct      = Decimal(str(RNG.choice([10, 15, 20, 25])))
        discount = (price * pct / 100).quantize(Decimal("0.01"))
    gross = (price - discount).quantize(Decimal("0.01"))

    gateway    = RNG.choice(list(PaymentGateway))
    pmt_status = PaymentStatus.FAILED if RNG.random() < 0.018 else PaymentStatus.SUCCESS

    days_old = (date(2026, 6, 10) - d).days
    if pmt_status == PaymentStatus.FAILED:
        ord_status = OrderStatus.UNFULFILLED
    elif days_old > 14:
        ord_status = RNG.choices(
            [OrderStatus.DELIVERED, OrderStatus.SHIPPED],
            weights=[0.90, 0.10],
        )[0]
    elif days_old > 5:
        ord_status = RNG.choices(
            [OrderStatus.DELIVERED, OrderStatus.SHIPPED, OrderStatus.PROCESSING],
            weights=[0.55, 0.35, 0.10],
        )[0]
    else:
        ord_status = RNG.choices(
            [OrderStatus.SHIPPED, OrderStatus.PROCESSING, OrderStatus.UNFULFILLED],
            weights=[0.50, 0.40, 0.10],
        )[0]

    # ~1.4% of delivered orders get refunded
    if pmt_status == PaymentStatus.SUCCESS and ord_status == OrderStatus.DELIVERED and RNG.random() < 0.014:
        pmt_status = PaymentStatus.REFUNDED

    shipping = (
        Decimal("0.00") if (price > Decimal("100") or promo)
        else Decimal(str(RNG.choice([0.00, 3.99, 4.99, 5.99, 6.99, 9.99, 11.99, 14.99])))
    )

    country, state = RNG.choice(SHIPPING_LOCATIONS)
    est_days        = RNG.randint(3, 10)
    est_delivery    = d + timedelta(days=est_days)
    actual_delivery = (
        d + timedelta(days=est_days + RNG.randint(-1, 2))
        if ord_status == OrderStatus.DELIVERED
        else None
    )

    order_dt = datetime(d.year, d.month, d.day, _hour(), RNG.randint(0, 59))

    return {
        "line_item_id":      line_id,
        "order_id":          order_id,
        "customer_id":       cust_id,
        "product_id":        prod_id,
        "quantity":          1,
        "unit_retail_price": price,
        "discount_applied":  discount,
        "gross_revenue":     gross,
        "payment_gateway":   gateway,
        "payment_status":    pmt_status,
        "shipping_country":  country,
        "shipping_state":    state,
        "shipping_cost":     shipping,
        "order_status":      ord_status,
        "checkout_device":   RNG.choice(list(CheckoutDevice)),
        "estimated_delivery": est_delivery,
        "actual_delivery":   actual_delivery,
        "promo_code_used":   promo,
        "created_at":        order_dt,
    }


def _make_campaigns_for_month(year: int, month: int, counter: list[int]) -> list[dict]:
    mi       = month - 1
    ym_label = f"{year}{month:02d}"
    dt_start = datetime(year, month, 1, 8, 0)

    prod_ids = [p[0] for p in PRODUCTS]
    weights  = [BASE_WEIGHTS[i] * SEASONAL[pid][mi] for i, pid in enumerate(prod_ids)]

    channel_plan = [
        (MarketingChannel.FACEBOOK_ADS, RNG.randint(2, 3)),
        (MarketingChannel.GOOGLE_ADS,   2),
        (MarketingChannel.TIKTOK_ADS,   RNG.randint(1, 2)),
        (MarketingChannel.EMAIL,        RNG.randint(1, 2)),
    ]

    rows: list[dict] = []
    for channel, count in channel_plan:
        ch = CH_CODE[channel]
        for i in range(count):
            counter[0] += 1
            camp_id     = f"CAMP-{ch}-H{counter[0]:05d}"
            prod_id     = RNG.choices(prod_ids, weights=weights)[0]

            daily_budget    = Decimal(str(RNG.choice([30, 50, 60, 80, 100, 120, 150, 200, 250])))
            spend_frac      = RNG.uniform(0.55, 1.00)
            total_spend     = (daily_budget * Decimal(str(round(spend_frac, 2)))).quantize(Decimal("0.01"))
            impressions     = RNG.randint(3000, 55000)
            ctr             = Decimal(str(round(RNG.uniform(1.5, 5.5), 2)))
            clicks          = max(1, int(impressions * float(ctr) / 100))
            cpc             = (total_spend / clicks).quantize(Decimal("0.01"))
            roas            = RNG.uniform(1.2, 9.0)
            attributed_rev  = (total_spend * Decimal(str(round(roas, 2)))).quantize(Decimal("0.01"))

            if spend_frac >= 0.99:
                status = CampaignStatus.BUDGET_EXHAUSTED
            elif (year < 2026) or (year == 2026 and month < 6):
                status = RNG.choices(
                    [CampaignStatus.COMPLETED, CampaignStatus.BUDGET_EXHAUSTED],
                    weights=[0.65, 0.35],
                )[0]
            else:
                status = CampaignStatus.ACTIVE

            n_hours    = RNG.randint(4, 8)
            hours_list = sorted(RNG.sample(range(8, 22), min(n_hours, 14)))
            per_h      = float(total_spend) / len(hours_list)
            hourly_log = [
                {"hour": h, "spend": round(per_h + RNG.uniform(-4.0, 4.0), 2)}
                for h in hours_list
            ]

            rows.append({
                "campaign_id":       camp_id,
                "campaign_name":     f"{ch}_{prod_id.replace('-', '_')}_{ym_label}_{i+1:02d}",
                "channel":           channel,
                "target_product_id": prod_id,
                "target_audience":   RNG.choice(AUDIENCES),
                "daily_budget":      daily_budget,
                "total_spend_today": total_spend,
                "impressions":       impressions,
                "clicks":            clicks,
                "ctr":               ctr,
                "cpc":               cpc,
                "attributed_revenue":attributed_rev,
                "campaign_status":   status,
                "tracking_utm_code": f"utm_source={ch.lower()}&utm_campaign={prod_id.lower()}_{ym_label}",
                "hourly_spend_log":  hourly_log,
                "created_at":        dt_start,
                "updated_at":        dt_start + timedelta(hours=RNG.randint(2, 12)),
            })

    return rows


def _make_ticket(order: dict, t_counter: list[int]) -> dict:
    t_counter[0] += 1
    ticket_id  = f"TKT-H{t_counter[0]:06d}"
    prod_id    = order["product_id"]
    title      = PROD_TITLES.get(prod_id, prod_id)
    order_id   = order["order_id"]
    est_date   = order.get("estimated_delivery", "N/A")
    order_date = order["created_at"].strftime("%Y-%m-%d")
    defect     = RNG.choice(DEFECTS)

    cat, subj_tpl, text_tpl = RNG.choice(TICKET_TEMPLATES)
    subject = subj_tpl.format(title=title, order_id=order_id, est_date=est_date)[:200]
    text    = text_tpl.format(
        title=title, order_id=order_id, est_date=est_date,
        order_date=order_date, defect=defect,
    )

    if cat == TicketCategory.PRODUCT_DEFECT:
        priority = RNG.choices(
            [TicketPriority.CRITICAL, TicketPriority.HIGH, TicketPriority.MEDIUM],
            weights=[0.20, 0.50, 0.30],
        )[0]
    else:
        priority = RNG.choices(
            [TicketPriority.HIGH, TicketPriority.MEDIUM, TicketPriority.LOW],
            weights=[0.35, 0.50, 0.15],
        )[0]

    days_ago = (date(2026, 6, 10) - order["created_at"].date()).days
    if days_ago > 7:
        status = RNG.choices(
            [TicketStatus.RESOLVED, TicketStatus.IN_PROGRESS],
            weights=[0.78, 0.22],
        )[0]
    else:
        status = RNG.choices(
            [TicketStatus.OPEN, TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED],
            weights=[0.35, 0.50, 0.15],
        )[0]

    res_type    = None
    resolved_at = None
    if status == TicketStatus.RESOLVED:
        res_type    = RNG.choice(list(ResolutionType))
        resolved_at = order["created_at"] + timedelta(days=RNG.randint(1, 6))

    ticket_dt = order["created_at"] + timedelta(hours=RNG.randint(1, 72))
    sentiment = Decimal(str(round(RNG.uniform(-0.95, -0.18), 2)))

    return {
        "ticket_id":         ticket_id,
        "customer_id":       order["customer_id"],
        "order_id":          order_id,
        "product_id":        prod_id,
        "subject":           subject,
        "customer_text":     text,
        "ticket_category":   cat,
        "priority":          priority,
        "ticket_status":     status,
        "sentiment_score":   sentiment,
        "assigned_agent_id": RNG.choice(
            ["AGENT-SUP-01", "AGENT-SUP-02", "AGENT-SUP-03",
             "AGENT-SUP-04", "AGENT-SUP-05", None]
        ),
        "resolution_type":   res_type,
        "created_at":        ticket_dt,
        "updated_at":        ticket_dt + timedelta(hours=RNG.randint(0, 24)),
        "resolved_at":       resolved_at,
    }


# ── Bulk-insert helper ────────────────────────────────────────────────────────

async def _bulk_insert(
    session,
    table,
    rows: list[dict],
    pk_col: str,
    label: str,
    batch_size: int = 1000,
) -> None:
    if not rows:
        return
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        stmt  = pg_insert(table).values(batch).on_conflict_do_nothing(index_elements=[pk_col])
        await session.execute(stmt)
        if i > 0 and i % 5000 == 0:
            await session.flush()
            print(f"    {label}: {i:,}/{len(rows):,} …")
    await session.commit()
    print(f"  [OK]{label}: {len(rows):,} rows committed.")


# ── Entry point ───────────────────────────────────────────────────────────────

async def seed_historical() -> None:
    """Seed 18 months of historical e-commerce data (idempotent)."""
    await create_db_and_tables()

    # Idempotency check — skip if historical rows already exist
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(func.count()).select_from(OrderItem).where(
                OrderItem.line_item_id.like("LINE-2025%")
            )
        )
        existing = result.scalar() or 0

    if existing > 100:
        print(f"Historical data already present ({existing:,} orders found). Skipping.")
        return

    print("Generating 2025-01-01 -> 2026-06-05 data ...")

    all_orders:    list[dict] = []
    all_campaigns: list[dict] = []
    all_tickets:   list[dict] = []

    camp_counter   = [0]
    ticket_counter = [0]
    seen_months: set[tuple[int, int]] = set()

    d = START
    while d <= END:
        month_key = (d.year, d.month)
        if month_key not in seen_months:
            seen_months.add(month_key)
            all_campaigns.extend(_make_campaigns_for_month(d.year, d.month, camp_counter))

        n_orders = _daily_volume(d)
        weights  = _product_weights(d)

        for seq in range(1, n_orders + 1):
            pid, price, promos = RNG.choices(PRODUCTS, weights=weights)[0]
            row = _make_order(d, seq, pid, price, promos)
            all_orders.append(row)
            if RNG.random() < 0.035:
                all_tickets.append(_make_ticket(row, ticket_counter))

        d += timedelta(days=1)

    print(
        f"Generated  {len(all_orders):,} orders | "
        f"{len(all_campaigns):,} campaigns | "
        f"{len(all_tickets):,} tickets\n"
        f"Inserting into PostgreSQL ..."
    )

    async with AsyncSessionLocal() as session:
        print("  Orders …")
        await _bulk_insert(session, OrderItem.__table__, all_orders, "line_item_id", "orders")

        print("  Campaigns …")
        await _bulk_insert(session, MarketingCampaign.__table__, all_campaigns, "campaign_id", "campaigns")

        print("  Tickets …")
        await _bulk_insert(session, CustomerSupportTicket.__table__, all_tickets, "ticket_id", "tickets")

    total_revenue = sum(float(r["gross_revenue"]) for r in all_orders)
    print(
        f"\n[DONE] Historical seed complete.\n"
        f"  Orders    : {len(all_orders):,}\n"
        f"  Campaigns : {len(all_campaigns):,}\n"
        f"  Tickets   : {len(all_tickets):,}\n"
        f"  Revenue   : ${total_revenue:,.2f}"
    )


if __name__ == "__main__":
    asyncio.run(seed_historical())
