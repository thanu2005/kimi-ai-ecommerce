"""Inventory-domain MCP tools.

All eight tools in this module interact exclusively with the ``products_inventory``
and ``order_items`` tables.

Read tools (safe to call during any agent analysis cycle):
    - resolve_product_identifiers
    - check_stock_status
    - get_brand_inventory_report
    - get_inventory_ledgers
    - get_incoming_supplier_orders
    - get_logistics_and_dimensions

Write / action tools (must only be called from the HITL execute_approved_actions
node after explicit operator approval):
    - update_safety_stock_trigger
    - restock_product_emergency

Registration
------------
Called once during server startup via::

    from mcp_server.tools.inventory import register
    register(mcp)
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import datetime
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update

from app.db.models.catalog import ProductInventory
from app.db.models.catalog import RestockStatus
from app.db.models.sales import OrderItem
from app.db.session import get_session

log = logging.getLogger(__name__)


def register(mcp) -> None:
    """Register all inventory-domain tools onto the provided FastMCP instance.

    Parameters
    ----------
    mcp : FastMCP
        The shared FastMCP application instance created in ``mcp_server.server``.
    """

    # ----------------------------------------------------------------------- #
    #  READ TOOLS                                                               #
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    async def resolve_product_identifiers(name_or_keyword: str) -> dict:
        """Resolve a fuzzy product name or keyword to matching catalog product IDs.

        Performs a case-insensitive substring search across the ``title``,
        ``sku``, and ``brand`` columns in ``products_inventory``.  This is the
        semantic bridge between natural language product references and the
        exact ``product_id`` primary keys required by all other inventory tools.

        **This tool must be called first** whenever the user query references a
        product by name, brand, or partial description rather than a known
        ``product_id``.  Do NOT guess or fabricate product IDs — always resolve
        them through this tool before calling ``check_stock_status`` or any
        other product-specific tool.

        Search behaviour
        ----------------
        - Matches are returned if ``name_or_keyword`` appears as a substring in
          ``title``, ``sku``, or ``brand`` (case-insensitive).
        - Returns all matching products — the agent should inspect the list and
          pick the most semantically appropriate ``product_id`` for subsequent
          tool calls.
        - Returns an empty ``matches`` list (not an error) when no products match.

        Parameters
        ----------
        name_or_keyword : str
            Free-text product name, partial SKU, or brand string to search for
            (e.g., ``"leather jacket"``, ``"PROD-LJ"``, ``"Nike"``).

        Returns
        -------
        dict
            Keys:
            - query          : str — echoed search term.
            - match_count    : int — number of matching products.
            - matches        : list[dict] — each entry has:
                  product_id, title, sku, brand.
        """
        log.info(f"📞 [INVENTORY] resolve_product_identifiers called | name_or_keyword={name_or_keyword}")
        pattern = f"%{name_or_keyword}%"

        async with get_session() as session:
            result = await session.execute(
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
            rows = result.all()

        matches = [
            {
                "product_id": r.product_id,
                "title": r.title,
                "sku": r.sku,
                "brand": r.brand,
            }
            for r in rows
        ]
        return {
            "query": name_or_keyword,
            "match_count": len(matches),
            "matches": matches,
        }

    @mcp.tool()
    async def check_stock_status(product_id: str) -> dict:
        """Return the live stock position and replenishment trigger state for a SKU.

        Queries the ``products_inventory`` table and returns five key inventory
        health indicators in a flat dictionary so the Inventory Agent can decide
        whether a product is at risk, already in a replenishment pipeline, or
        healthy.

        Fields returned
        ---------------
        - product_id         : Unique product primary key (echoed back for tracing).
        - title              : Human-readable product name.
        - physical_stock     : Raw on-hand unit count currently sitting in the
                               warehouse, including units pending dispatch.
        - allocated_stock    : Units already reserved for confirmed open orders
                               that have not yet been physically shipped.
        - available_stock    : Computed as ``physical_stock - allocated_stock``.
                               This is the true sellable quantity at any instant.
        - safety_stock_level : Minimum on-hand threshold below which the automated
                               replenishment trigger should fire.
        - restock_status     : Current replenishment pipeline state.  One of:
                               ``NORMAL`` | ``BELOW_SAFETY`` | ``PO_PLACED`` |
                               ``BACKORDERED``.

        Parameters
        ----------
        product_id : str
            The unique product identifier (e.g., ``'PROD-GC-010'``) as stored
            in the ``products_inventory.product_id`` primary key column.

        Returns
        -------
        dict
            Flat dictionary with keys: product_id, title, physical_stock,
            allocated_stock, available_stock, safety_stock_level,
            restock_status.
            Returns ``{"error": "..."}`` if the product_id does not exist.
        """       
        log.info(f" [INVENTORY] check_stock_status called | product_id={product_id}")        
        async with get_session() as session:
            result = await session.execute(
                select(
                    ProductInventory.product_id,
                    ProductInventory.title,
                    ProductInventory.physical_stock,
                    ProductInventory.allocated_stock,
                    ProductInventory.safety_stock_level,
                    ProductInventory.restock_status,
                ).where(ProductInventory.product_id == product_id)
            )
            row = result.first()

        if row is None:
            return {"error": f"Product '{product_id}' not found in catalog."}

        restock_val = (
            row.restock_status.value
            if hasattr(row.restock_status, "value")
            else str(row.restock_status)
        )
        return {
            "product_id": row.product_id,
            "title": row.title,
            "physical_stock": row.physical_stock,
            "allocated_stock": row.allocated_stock,
            "available_stock": row.physical_stock - row.allocated_stock,
            "safety_stock_level": row.safety_stock_level,
            "restock_status": restock_val,
        }

    @mcp.tool()
    async def get_inventory_ledgers(product_id: str, date: str) -> dict:
        """Return a chronological stock-movement ledger for a product on a given date.

        Reconstructs a day's stock ledger by querying the ``order_items`` table
        for every sales transaction involving the specified product on the given
        calendar day.  Each entry represents a discrete stock deduction event
        (a unit sold) with its associated timestamp, order reference, quantity,
        and fulfilment state.

        The ledger is sorted ascending by ``created_at`` so the Inventory Agent
        can pinpoint the exact minute stock crossed a safety threshold.  This
        timestamp is the primary anchor for cross-domain correlation during the
        reflection loop — the Sales, Marketing, and Support agents all align
        their event timelines to this moment.

        Parameters
        ----------
        product_id : str
            The unique product identifier (e.g., ``'PROD-YM-005'``) as stored in
            ``products_inventory.product_id``.
        date : str
            Calendar date in ISO-8601 format ``'YYYY-MM-DD'``
            (e.g., ``'2026-06-06'``).  All ledger entries whose ``created_at``
            timestamp falls within this calendar day (00:00:00 – 23:59:59) are
            returned.

        Returns
        -------
        dict
            Keys:
            - product_id        : str
            - date              : str
            - total_units_sold  : int — sum of all ``quantity`` values in the ledger.
            - entry_count       : int — number of discrete transactions.
            - entries           : list[dict] — each entry contains:
                  line_item_id, order_id, quantity, unit_retail_price (str),
                  order_status, payment_status, created_at (ISO-8601 string).

            Returns ``{"error": "..."}`` on an invalid date format.
        """
        try:
            target = date_type.fromisoformat(date)
        except ValueError:
            return {"error": f"Invalid date format '{date}'. Expected YYYY-MM-DD."}

        day_start = datetime(target.year, target.month, target.day, 0, 0, 0)
        day_end = datetime(target.year, target.month, target.day, 23, 59, 59)

        async with get_session() as session:
            result = await session.execute(
                select(OrderItem)
                .where(
                    OrderItem.product_id == product_id,
                    OrderItem.created_at >= day_start,
                    OrderItem.created_at <= day_end,
                )
                .order_by(OrderItem.created_at.asc())
            )
            rows = result.scalars().all()

        if not rows:
            return {
                "product_id": product_id,
                "date": date,
                "total_units_sold": 0,
                "entry_count": 0,
                "entries": [],
            }

        entries = [
            {
                "line_item_id": r.line_item_id,
                "order_id": r.order_id,
                "quantity": r.quantity,
                "unit_retail_price": str(r.unit_retail_price),
                "order_status": (
                    r.order_status.value
                    if hasattr(r.order_status, "value")
                    else str(r.order_status)
                ),
                "payment_status": (
                    r.payment_status.value
                    if hasattr(r.payment_status, "value")
                    else str(r.payment_status)
                ),
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
        return {
            "product_id": product_id,
            "date": date,
            "total_units_sold": sum(r.quantity for r in rows),
            "entry_count": len(entries),
            "entries": entries,
        }

    @mcp.tool()
    async def get_incoming_supplier_orders(product_id: str) -> dict:
        """Return pending supplier replenishment order details for a product.

        Reads the ``products_inventory`` table to surface supplier pipeline
        information: the assigned supplier ID, standard lead time in calendar
        days, configured reorder quantity, current restock status, and a
        computed estimated arrival date calculated as today + lead_time_days.

        This tool is critical for operational decision-making.  Knowing whether
        a replacement shipment arrives in 3 days versus 18 days completely changes
        which corrective action the Inventory Agent should propose:

        - Short lead time  → advise customers of minor delay; hold campaigns.
        - Long lead time   → trigger emergency local sourcing; pause ad spend;
                             escalate to support for proactive outreach.

        The ``po_active`` boolean flag indicates whether a purchase order is
        already in the supplier pipeline (``PO_PLACED`` or ``BACKORDERED``),
        preventing duplicate emergency PO submissions.

        Parameters
        ----------
        product_id : str
            The unique product identifier (e.g., ``'PROD-GC-010'``) as stored
            in ``products_inventory.product_id``.

        Returns
        -------
        dict
            Keys:
            - product_id              : str
            - title                   : str
            - supplier_id             : str
            - supplier_lead_time_days : int
            - reorder_quantity        : int
            - restock_status          : str — current replenishment pipeline state.
            - estimated_arrival       : str — ISO date computed as today +
                                        supplier_lead_time_days.
            - po_active               : bool — True if status is ``PO_PLACED``
                                        or ``BACKORDERED``; False otherwise.

            Returns ``{"error": "..."}`` if the product_id does not exist.
        """
        async with get_session() as session:
            result = await session.execute(
                select(
                    ProductInventory.product_id,
                    ProductInventory.title,
                    ProductInventory.supplier_id,
                    ProductInventory.supplier_lead_time,
                    ProductInventory.reorder_quantity,
                    ProductInventory.restock_status,
                ).where(ProductInventory.product_id == product_id)
            )
            row = result.first()

        if row is None:
            return {"error": f"Product '{product_id}' not found in catalog."}

        today = date_type.today()
        estimated_arrival = (today + timedelta(days=row.supplier_lead_time)).isoformat()
        restock_val = (
            row.restock_status.value
            if hasattr(row.restock_status, "value")
            else str(row.restock_status)
        )
        po_active = restock_val in ("PO_PLACED", "BACKORDERED")

        return {
            "product_id": row.product_id,
            "title": row.title,
            "supplier_id": row.supplier_id,
            "supplier_lead_time_days": row.supplier_lead_time,
            "reorder_quantity": row.reorder_quantity,
            "restock_status": restock_val,
            "estimated_arrival": estimated_arrival,
            "po_active": po_active,
        }

    @mcp.tool()
    async def get_logistics_and_dimensions(product_id: str) -> dict:
        """Return the physical shipping specifications and DIM weight analysis for a SKU.

        Retrieves dimensional and weight data from ``products_inventory`` and
        computes the carrier volumetric (DIM) weight using the standard 5 000
        divisor formula::

            volumetric_weight_kg = (length_cm × width_cm × height_cm) / 5000

        When the volumetric weight exceeds the actual physical weight, most
        carriers bill at the higher volumetric rate.  This silently erodes
        per-transaction margins and can make certain products unprofitable to
        ship at current retail prices — a finding the Inventory Agent surfaces
        in the whiteboard for the Sales Agent to cross-reference against margin
        data.

        Parameters
        ----------
        product_id : str
            The unique product identifier (e.g., ``'PROD-LS-013'``) as stored
            in ``products_inventory.product_id``.

        Returns
        -------
        dict
            Keys:
            - product_id               : str
            - title                    : str
            - weight_kg                : float — actual physical weight.
            - length_cm                : int
            - width_cm                 : int
            - height_cm                : int
            - volumetric_weight_kg     : float — DIM weight rounded to 3 dp.
            - billed_weight_kg         : float — max(actual, volumetric).
            - dim_weight_exceeds_actual: bool — True signals a margin risk flag.

            Returns ``{"error": "..."}`` if the product_id does not exist.
        """
        async with get_session() as session:
            result = await session.execute(
                select(
                    ProductInventory.product_id,
                    ProductInventory.title,
                    ProductInventory.weight_kg,
                    ProductInventory.length_cm,
                    ProductInventory.width_cm,
                    ProductInventory.height_cm,
                ).where(ProductInventory.product_id == product_id)
            )
            row = result.first()

        if row is None:
            return {"error": f"Product '{product_id}' not found in catalog."}

        volumetric = round(
            (row.length_cm * row.width_cm * row.height_cm) / 5000, 3
        )
        actual = float(row.weight_kg)
        billed = max(actual, volumetric)

        return {
            "product_id": row.product_id,
            "title": row.title,
            "weight_kg": actual,
            "length_cm": row.length_cm,
            "width_cm": row.width_cm,
            "height_cm": row.height_cm,
            "volumetric_weight_kg": volumetric,
            "billed_weight_kg": round(billed, 3),
            "dim_weight_exceeds_actual": volumetric > actual,
        }

    @mcp.tool()
    async def get_brand_inventory_report(brand: str) -> dict:
        """Return an aggregated inventory summary for all products belonging to a brand.

        Queries ``products_inventory`` filtering by ``brand`` (case-insensitive
        substring match) and aggregates stock metrics across all matching SKUs.
        This resolves broad reporting requests such as "how is Nike inventory"
        without requiring the agent to call ``check_stock_status`` on each
        product individually.

        Metrics returned
        ----------------
        - total_skus             : int — total products matched for this brand.
        - skus_below_safety      : int — products where physical_stock <= safety_stock_level.
        - skus_at_zero           : int — products with physical_stock = 0.
        - skus_backordered       : int — products with restock_status = BACKORDERED.
        - total_physical_stock   : int — sum of physical_stock across all matched SKUs.
        - total_allocated_stock  : int — sum of allocated_stock across all matched SKUs.
        - total_available_stock  : int — total_physical_stock - total_allocated_stock.
        - products               : list[dict] — one entry per matched SKU with:
              product_id, title, sku, physical_stock, allocated_stock,
              available_stock, safety_stock_level, restock_status.
              Sorted by available_stock ascending (most critical first).

        Parameters
        ----------
        brand : str
            Brand name to search for (case-insensitive substring match).
            (e.g., ``"Nike"``, ``"Apple"``, ``"leather"``).

        Returns
        -------
        dict
            Keys:
            - brand                  : str — echoed search term.
            - match_count            : int
            - total_physical_stock   : int
            - total_allocated_stock  : int
            - total_available_stock  : int
            - skus_below_safety      : int
            - skus_at_zero           : int
            - skus_backordered       : int
            - products               : list[dict]

            Returns ``{"error": "..."}`` if no products match the brand.
        """
        log.info(f"📞 [INVENTORY] get_brand_inventory_report called | brand={brand}")
        pattern = f"%{brand}%"

        async with get_session() as session:
            result = await session.execute(
                select(
                    ProductInventory.product_id,
                    ProductInventory.title,
                    ProductInventory.sku,
                    ProductInventory.physical_stock,
                    ProductInventory.allocated_stock,
                    ProductInventory.safety_stock_level,
                    ProductInventory.restock_status,
                ).where(
                    ProductInventory.brand.ilike(pattern)
                ).order_by(
                    (ProductInventory.physical_stock - ProductInventory.allocated_stock).asc()
                )
            )
            rows = result.all()

        if not rows:
            return {"error": f"No products found matching brand '{brand}'."}

        products = []
        for r in rows:
            restock_val = (
                r.restock_status.value
                if hasattr(r.restock_status, "value")
                else str(r.restock_status)
            )
            available = r.physical_stock - r.allocated_stock
            products.append({
                "product_id": r.product_id,
                "title": r.title,
                "sku": r.sku,
                "physical_stock": r.physical_stock,
                "allocated_stock": r.allocated_stock,
                "available_stock": available,
                "safety_stock_level": r.safety_stock_level,
                "restock_status": restock_val,
            })

        total_physical = sum(p["physical_stock"] for p in products)
        total_allocated = sum(p["allocated_stock"] for p in products)
        total_available = sum(p["available_stock"] for p in products)
        skus_below_safety = sum(
            1 for p in products if p["physical_stock"] <= p["safety_stock_level"]
        )
        skus_at_zero = sum(1 for p in products if p["physical_stock"] == 0)
        skus_backordered = sum(1 for p in products if p["restock_status"] == "BACKORDERED")

        return {
            "brand": brand,
            "match_count": len(products),
            "total_physical_stock": total_physical,
            "total_allocated_stock": total_allocated,
            "total_available_stock": total_available,
            "skus_below_safety": skus_below_safety,
            "skus_at_zero": skus_at_zero,
            "skus_backordered": skus_backordered,
            "products": products,
        }

    # ----------------------------------------------------------------------- #
    #  WRITE / ACTION TOOLS  (HITL-gated)                                      #
    # ----------------------------------------------------------------------- #

    @mcp.tool()
    async def update_safety_stock_trigger(
        product_id: str, new_threshold: int
    ) -> dict:
        """Modify the safety stock threshold for a product in the inventory catalog.

        This is a structural optimisation write tool.  It updates the
        ``safety_stock_level`` column in ``products_inventory`` for the specified
        product, permanently raising or lowering the automated replenishment
        trigger point.

        When to use
        -----------
        - **Raise threshold** when a product consistently sells out before its
          supplier lead time can fulfil a replenishment cycle.  The higher
          threshold ensures a PO is triggered earlier, providing a larger buffer.
        - **Lower threshold** when a product chronically over-accumulates buffer
          stock, tying up warehouse capacity and working capital.

        Post-update status re-evaluation
        ---------------------------------
        After writing the new threshold this tool immediately re-evaluates
        ``restock_status``:

        - available_stock (physical − allocated) <= new_threshold  →  ``BELOW_SAFETY``
        - available_stock > new_threshold (and status was NORMAL/BELOW_SAFETY)
          →  ``NORMAL``
        - ``PO_PLACED`` and ``BACKORDERED`` statuses are left unchanged because
          a supplier order is already in-flight.

        Parameters
        ----------
        product_id    : str — Target product primary key (e.g., ``'PROD-GC-010'``).
        new_threshold : int — New safety stock level in whole units.  Must be >= 0.

        Returns
        -------
        dict
            Keys:
            - success              : bool
            - product_id           : str
            - old_threshold        : int
            - new_threshold        : int
            - restock_status_after : str — status after re-evaluation.
            - message              : str — human-readable confirmation.

            Returns ``{"error": "..."}`` if the product_id is not found or
            ``new_threshold`` is negative.
        """
        if new_threshold < 0:
            return {"error": "new_threshold must be a non-negative integer."}

        async with get_session() as session:
            result = await session.execute(
                select(
                    ProductInventory.product_id,
                    ProductInventory.physical_stock,
                    ProductInventory.allocated_stock,
                    ProductInventory.safety_stock_level,
                    ProductInventory.restock_status,
                ).where(ProductInventory.product_id == product_id)
            )
            row = result.first()

            if row is None:
                return {"error": f"Product '{product_id}' not found in catalog."}

            old_threshold = row.safety_stock_level
            available = row.physical_stock - row.allocated_stock
            current_status = row.restock_status

            if current_status in (RestockStatus.NORMAL, RestockStatus.BELOW_SAFETY):
                new_status = (
                    RestockStatus.BELOW_SAFETY
                    if available <= new_threshold
                    else RestockStatus.NORMAL
                )
            else:
                new_status = current_status

            await session.execute(
                update(ProductInventory)
                .where(ProductInventory.product_id == product_id)
                .values(
                    safety_stock_level=new_threshold,
                    restock_status=new_status,
                )
            )

        new_status_val = (
            new_status.value if hasattr(new_status, "value") else str(new_status)
        )
        return {
            "success": True,
            "product_id": product_id,
            "old_threshold": old_threshold,
            "new_threshold": new_threshold,
            "restock_status_after": new_status_val,
            "message": (
                f"Safety stock threshold for '{product_id}' updated from "
                f"{old_threshold} to {new_threshold} units.  "
                f"Restock status is now '{new_status_val}'."
            ),
        }

    @mcp.tool()
    async def restock_product_emergency(product_id: str, quantity: int) -> dict:
        """Trigger an emergency supplier purchase order and mark the product as PO_PLACED.

        This is the primary HITL-gated action tool for the Inventory Agent.
        It **must only be invoked from within the** ``execute_approved_actions``
        **node** after explicit human approval via the dashboard interrupt
        checkpoint.  Direct agent invocation outside that node violates the
        system's human-in-the-loop contract.

        What this tool does
        -------------------
        Performs two atomic write operations inside a single database transaction:

        1. Sets ``restock_status`` to ``PO_PLACED`` in ``products_inventory``.
        2. Increments ``reorder_quantity`` by ``quantity``, representing the
           emergency PO volume stacked on top of the standard reorder cycle.

        The tool also computes and returns an estimated arrival date using the
        product's ``supplier_lead_time`` so the operator dashboard and downstream
        agents can display a precise recovery ETA.

        Idempotency note
        ----------------
        If ``restock_status`` is already ``PO_PLACED``, the tool will still
        execute (adding to the PO quantity) but will include a warning in the
        response message.  Callers should check ``get_incoming_supplier_orders``
        first to avoid duplicate emergency submissions.

        Parameters
        ----------
        product_id : str — Target product primary key (e.g., ``'PROD-GC-010'``).
        quantity   : int — Number of units to include in this emergency PO.
                     Must be a positive integer (> 0).

        Returns
        -------
        dict
            Keys:
            - success           : bool
            - product_id        : str
            - emergency_po_qty  : int — quantity submitted in this PO.
            - restock_status    : str — always ``'PO_PLACED'`` on success.
            - estimated_arrival : str — ISO date (today + supplier_lead_time_days).
            - supplier_id       : str
            - message           : str — human-readable confirmation with ETA.

            Returns ``{"error": "..."}`` if the product_id is not found or
            ``quantity`` is not a positive integer.
        """
        if quantity <= 0:
            return {"error": "quantity must be a positive integer."}

        async with get_session() as session:
            result = await session.execute(
                select(
                    ProductInventory.product_id,
                    ProductInventory.title,
                    ProductInventory.supplier_id,
                    ProductInventory.supplier_lead_time,
                    ProductInventory.reorder_quantity,
                    ProductInventory.restock_status,
                ).where(ProductInventory.product_id == product_id)
            )
            row = result.first()

            if row is None:
                return {"error": f"Product '{product_id}' not found in catalog."}

            already_active = (
                row.restock_status.value
                if hasattr(row.restock_status, "value")
                else str(row.restock_status)
            ) == "PO_PLACED"

            await session.execute(
                update(ProductInventory)
                .where(ProductInventory.product_id == product_id)
                .values(
                    restock_status=RestockStatus.PO_PLACED,
                    reorder_quantity=row.reorder_quantity + quantity,
                )
            )

        today = date_type.today()
        estimated_arrival = (
            today + timedelta(days=row.supplier_lead_time)
        ).isoformat()

        warning = (
            "  WARNING: a PO was already active for this product; "
            "emergency quantity appended to existing order."
            if already_active
            else ""
        )
        return {
            "success": True,
            "product_id": product_id,
            "emergency_po_qty": quantity,
            "restock_status": "PO_PLACED",
            "estimated_arrival": estimated_arrival,
            "supplier_id": row.supplier_id,
            "message": (
                f"Emergency PO for {quantity} units of '{product_id}' submitted "
                f"to supplier '{row.supplier_id}'.  Restock status set to "
                f"PO_PLACED.  Estimated arrival: {estimated_arrival} "
                f"({row.supplier_lead_time} day lead time).{warning}"
            ),
        }
