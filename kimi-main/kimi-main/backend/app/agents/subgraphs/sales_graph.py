"""Sales domain subgraph agent."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.config.definitions import SALES_CONFIG


class SalesAgent(BaseAgent):
    """Tracks revenue trends, payment gateway health, and order device split."""

    agent_config = SALES_CONFIG

