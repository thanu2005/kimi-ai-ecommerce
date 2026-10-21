"""Inventory domain subgraph agent."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.config.definitions import INVENTORY_CONFIG


class InventoryAgent(BaseAgent):
    """Monitors stock levels, restock triggers, and supplier pipeline health."""

    agent_config = INVENTORY_CONFIG

