"""Seeding script for incident memory testing.

Populates the incident_memories table with realistic test scenarios so you can
verify cross-thread retrieval and action-effectiveness features.

Usage:
    cd backend
    uv run python -m app.services.test_incident_seeder
"""

import asyncio
import json
from datetime import datetime, timedelta

from app.db.models.agent_memory import IncidentMemory
from app.db.session import create_db_and_tables, get_session


async def seed_incidents() -> None:
    """Create realistic test incidents for memory retrieval."""
    await create_db_and_tables()

    test_incidents = [
        IncidentMemory(
            incident_id="inc-test-001",
            run_id="run-test-20260618-001",
            thread_id="thread-test-001",
            query_text="Sales dropped 40% in the last 6 hours, what happened?",
            incident_type="SALES_DROP",
            severity="HIGH",
            time_window="2026-06-18T00:00:00 to 2026-06-18T06:00:00",
            domains_json=["sales", "payment", "support"],
            symptoms_text=(
                "sales: GMV dropped from $50k/hour to $30k/hour at 03:15 UTC | "
                "payment: Stripe gateway failure_rate jumped from 2% to 15% | "
                "support: Checkout error tickets surged from 5 to 47 in 30 min"
            ),
            root_cause_text=(
                "Stripe API integration timeout during regional payment gateway failover. "
                "Customers received checkout errors but could retry. "
                "Root cause: Stripe us-east-1 regional degradation (later confirmed in incident report)."
            ),
            actions_executed_json=[
                {
                    "action": "pause_marketing_campaign",
                    "result": "Paused campaign C-0891 (free-shipping-promo) to reduce checkout traffic",
                    "success": True,
                },
                {
                    "action": "adjust_campaign_budget",
                    "result": "Reduced spend on high-traffic campaigns by 35%",
                    "success": True,
                },
            ],
            outcome_metrics_json={
                "execution_count": 2,
                "successful_execution_count": 2,
                "failure_execution_count": 0,
                "domain_count": 3,
            },
            outcome_label="IMPROVED",
            evidence_refs_json=[{"run_id": "run-test-20260618-001", "thread_id": "thread-test-001"}],
            created_at=datetime.utcnow() - timedelta(days=2),
            updated_at=datetime.utcnow() - timedelta(days=2),
            vectorized_at=datetime.utcnow() - timedelta(days=2),
        ),
        IncidentMemory(
            incident_id="inc-test-002",
            run_id="run-test-20260617-001",
            thread_id="thread-test-002",
            query_text="Inventory stockout for PROD-SH-045, customers complaining",
            incident_type="INVENTORY_SHORTAGE",
            severity="MEDIUM",
            time_window="2026-06-17T12:00:00 to 2026-06-17T18:00:00",
            domains_json=["inventory", "sales", "support"],
            symptoms_text=(
                "inventory: PROD-SH-045 (Yoga Mat) physical_stock = 0 (safety_stock = 100) | "
                "sales: Out-of-stock page views increased 250% | "
                "support: Product unavailability complaints increased from 2 to 31 per hour"
            ),
            root_cause_text=(
                "Supplier delay: Emergency restock order (500 units) expected 2026-06-15, "
                "arrived 2026-06-17 16:45. Warehouse intake took 2 hours, released to system 18:45. "
                "During 6-hour gap, customers saw 'out of stock'. Marketing campaign was still active, "
                "driving demand to zero-inventory product."
            ),
            actions_executed_json=[
                {
                    "action": "restock_product_emergency",
                    "result": "Fast-tracked 200 units PROD-SH-045 from warehouse backstock",
                    "success": True,
                },
                {
                    "action": "pause_marketing_campaign",
                    "result": "Paused yoga mat promotion campaigns (C-0765, C-0789)",
                    "success": True,
                },
            ],
            outcome_metrics_json={
                "execution_count": 2,
                "successful_execution_count": 2,
                "failure_execution_count": 0,
                "domain_count": 3,
            },
            outcome_label="IMPROVED",
            evidence_refs_json=[{"run_id": "run-test-20260617-001", "thread_id": "thread-test-002"}],
            created_at=datetime.utcnow() - timedelta(days=1),
            updated_at=datetime.utcnow() - timedelta(days=1),
            vectorized_at=datetime.utcnow() - timedelta(days=1),
        ),
        IncidentMemory(
            incident_id="inc-test-003",
            run_id="run-test-20260616-001",
            thread_id="thread-test-003",
            query_text="Campaign ROAS dropped below 1.0, audit spend",
            incident_type="MARKETING_EFFICIENCY",
            severity="LOW",
            time_window="2026-06-16T00:00:00 to 2026-06-16T24:00:00",
            domains_json=["marketing", "sales"],
            symptoms_text=(
                "marketing: Campaign C-0712 ROAS dropped from 1.8 to 0.6 overnight | "
                "marketing: Spend increased 400% but attributed revenue increased only 40% | "
                "sales: Product PROD-EL-032 orders did not follow spend increase (anomaly)"
            ),
            root_cause_text=(
                "Marketing campaign targeting changed to lookalike audiences (expanded by 5x). "
                "Lookalike audience had lower purchase intent. "
                "Meanwhile, product supply constraint (PROD-EL-032) meant orders couldn't scale. "
                "Campaign spent heavily but inventory sold out, wasting ad budget."
            ),
            actions_executed_json=[
                {
                    "action": "pause_marketing_campaign",
                    "result": "Paused campaign C-0712",
                    "success": True,
                },
                {
                    "action": "adjust_campaign_budget",
                    "result": "Reduced daily budget from $5000 to $500 for C-0701 (core campaign)",
                    "success": True,
                },
            ],
            outcome_metrics_json={
                "execution_count": 2,
                "successful_execution_count": 2,
                "failure_execution_count": 0,
                "domain_count": 2,
            },
            outcome_label="STABLE",
            evidence_refs_json=[{"run_id": "run-test-20260616-001", "thread_id": "thread-test-003"}],
            created_at=datetime.utcnow() - timedelta(days=2),
            updated_at=datetime.utcnow() - timedelta(days=2),
            vectorized_at=datetime.utcnow() - timedelta(days=2),
        ),
    ]

    async with get_session() as session:
        for incident in test_incidents:
            session.add(incident)
        await session.commit()

    print(f"✅ Seeded {len(test_incidents)} test incidents into incident_memories table.")
    print("\nTest incidents created:")
    for inc in test_incidents:
        print(
            f"  • {inc.incident_id} ({inc.incident_type}, {inc.severity}) — outcome={inc.outcome_label}"
        )
    print(
        "\n📝 Now run the frontend and try these prompts:\n"
        "  1. 'Has a sales drop happened before?'\n"
        "  2. 'What did we do last time inventory ran out?'\n"
        "  3. 'Did pausing campaigns help improve revenue in past incidents?'\n"
        "  4. 'Compare the last time we had a multi-domain anomaly (sales+payment+support)'\n"
    )


if __name__ == "__main__":
    asyncio.run(seed_incidents())
