"""LLM factory for the supervisor orchestrator."""

from __future__ import annotations

from langchain_openai import AzureChatOpenAI

from app.config import settings


def build_llm() -> AzureChatOpenAI:
    """Shared LLM instance for the supervisor's planning and synthesis nodes."""
    return AzureChatOpenAI(
        azure_endpoint=settings.dial_endpoint,
        azure_deployment=settings.dial_chat_deployment,
        api_version=settings.dial_api_version,
        api_key=settings.dial_api_key,
        default_headers={"Api-Key": settings.dial_api_key},
        temperature=0,
        max_retries=3,
    )
