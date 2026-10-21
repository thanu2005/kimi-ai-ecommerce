"""Marketing domain subgraph agent."""

from __future__ import annotations

from app.agents.base import BaseAgent
from app.agents.config.definitions import MARKETING_CONFIG


class MarketingAgent(BaseAgent):
    """Monitors campaign ROI, spend efficiency, and active promotions health."""

    agent_config = MARKETING_CONFIG

