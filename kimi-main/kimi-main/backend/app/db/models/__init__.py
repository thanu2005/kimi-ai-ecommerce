"""Consolidated model registry — import every SQLModel table here so that
SQLAlchemy's metadata object is fully populated before create_all / Alembic runs."""

from app.db.models.catalog import ProductInventory  # noqa: F401
from app.db.models.sales import OrderItem  # noqa: F401
from app.db.models.marketing import MarketingCampaign  # noqa: F401
from app.db.models.support import CustomerSupportTicket  # noqa: F401
from app.db.models.agent_memory import AgentRunMemory, IncidentMemory  # noqa: F401
from app.db.models.conversation_thread import ConversationThread  # noqa: F401
from app.db.models.conversation_message import ConversationMessage  # noqa: F401
