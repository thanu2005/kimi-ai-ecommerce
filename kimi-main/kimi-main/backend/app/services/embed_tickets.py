"""Qdrant ticket embedding ingestion script.

Reads every support ticket from ``customer_support_tickets``, generates
OpenAI ``text-embedding-3-small`` embeddings from a composite of each
ticket's ``subject`` and ``customer_text``, then upserts the resulting
vectors into the Qdrant ``support_ticket_embeddings`` collection.

The Qdrant payload stored alongside each vector matches the schema
defined in the project specification::

    {
        "ticket_id"            : str   (PK from PostgreSQL),
        "product_id"           : str,
        "ticket_category"      : str,
        "sentiment_score"      : float,
        "resolution_type"      : str | None,
        "created_at_timestamp" : int   (Unix epoch)
    }

Re-running this script is safe and idempotent — ``upsert`` will overwrite
any existing point that shares the same integer ID.

Usage (from backend/ directory)::

    uv run python -m app.services.embed_tickets
"""

from __future__ import annotations

import asyncio
import hashlib
import time

from sqlalchemy import select

from app.config import settings
from app.db.models.support import CustomerSupportTicket
from app.db.session import create_db_and_tables, get_session
# --------------------------------------------------------------------------- #
#  Constants                                                                   #
# --------------------------------------------------------------------------- #

COLLECTION_NAME = settings.qdrant_collection
VECTOR_SIZE = 1536          # text-embedding-3-small-1 output dimension
EMBEDDING_BATCH_SIZE = 20   # max tickets embedded per OpenAI API call


# --------------------------------------------------------------------------- #
#  Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _ticket_to_text(ticket: CustomerSupportTicket) -> str:
    """Concatenate subject and body into the embedding input string.

    Embedding a composite of both fields gives the vector richer semantic
    coverage — the subject contains the short intent while the body holds
    the emotional context that is critical for similarity matching.
    """
    return f"{ticket.subject}. {ticket.customer_text}"


def _stable_point_id(ticket_id: str) -> int:
    """Derive a stable, unique integer point ID from a ticket_id string.

    Qdrant requires integer or UUID point IDs.  We hash the ticket_id
    string into a 63-bit positive integer so the mapping is deterministic
    across ingestion runs (enabling idempotent upserts).
    """
    return int(hashlib.md5(ticket_id.encode()).hexdigest(), 16) % (2**63)


# --------------------------------------------------------------------------- #
#  Collection setup                                                            #
# --------------------------------------------------------------------------- #

async def _ensure_collection(client) -> None:
    """Create the Qdrant collection if it does not already exist."""
    from qdrant_client.http.models import Distance, VectorParams

    existing = await client.get_collections()
    names = [c.name for c in existing.collections]
    if COLLECTION_NAME not in names:
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )
        print(f"  Created Qdrant collection '{COLLECTION_NAME}'.")
    else:
        print(f"  Collection '{COLLECTION_NAME}' already exists — upserting into it.")


# --------------------------------------------------------------------------- #
#  Embedding                                                                   #
# --------------------------------------------------------------------------- #

async def _embed_batch(texts: list[str], embedder) -> list[list[float]]:
    """Return embeddings for a batch of text strings."""
    return await embedder.aembed_documents(texts)


# --------------------------------------------------------------------------- #
#  Main ingestion routine                                                      #
# --------------------------------------------------------------------------- #

async def ingest() -> None:
    """Fetch all tickets, embed them, and upsert into Qdrant."""
    from langchain_openai import AzureOpenAIEmbeddings
    from qdrant_client import AsyncQdrantClient
    from qdrant_client.http.models import PointStruct

    print("=== Ticket Embedding Ingestion ===")

    # 1. Ensure DB tables exist
    await create_db_and_tables()

    # 2. Fetch all tickets from PostgreSQL
    async with get_session() as session:
        result = await session.execute(select(CustomerSupportTicket))
        tickets: list[CustomerSupportTicket] = result.scalars().all()

    if not tickets:
        print("No tickets found in the database. Run the seeder first.")
        return
    print(f"  Found {len(tickets)} ticket(s) in database.")

    # 3. Build Azure DIAL-compatible embedder
    embedder = AzureOpenAIEmbeddings(
        azure_endpoint=settings.dial_endpoint,
        azure_deployment=settings.dial_embedding_deployment,
        api_version=settings.dial_api_version,
        api_key=settings.dial_api_key,
        default_headers={"Api-Key": settings.dial_api_key},
    )

    # 4. Connect to Qdrant and ensure collection exists
    client = AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    await _ensure_collection(client)

    # 5. Embed in batches and upsert
    total_upserted = 0
    for batch_start in range(0, len(tickets), EMBEDDING_BATCH_SIZE):
        batch = tickets[batch_start : batch_start + EMBEDDING_BATCH_SIZE]
        texts = [_ticket_to_text(t) for t in batch]

        print(f"  Embedding batch {batch_start + 1}–{batch_start + len(batch)} ...", end=" ")
        t0 = time.monotonic()
        vectors = await _embed_batch(texts, embedder)
        elapsed = round(time.monotonic() - t0, 2)
        print(f"done in {elapsed}s")

        points = []
        for ticket, vector in zip(batch, vectors):
            resolution = (
                ticket.resolution_type.value
                if ticket.resolution_type is not None and hasattr(ticket.resolution_type, "value")
                else (str(ticket.resolution_type) if ticket.resolution_type else None)
            )
            category = (
                ticket.ticket_category.value
                if hasattr(ticket.ticket_category, "value")
                else str(ticket.ticket_category)
            )
            points.append(
                PointStruct(
                    id=_stable_point_id(ticket.ticket_id),
                    vector=vector,
                    payload={
                        "ticket_id": ticket.ticket_id,
                        "product_id": ticket.product_id or "",
                        "ticket_category": category,
                        "sentiment_score": float(ticket.sentiment_score),
                        "resolution_type": resolution,
                        "created_at_timestamp": int(ticket.created_at.timestamp()),
                    },
                )
            )

        await client.upsert(collection_name=COLLECTION_NAME, points=points)
        total_upserted += len(points)

    await client.close()

    print(
        f"\nIngestion complete — {total_upserted} ticket vector(s) upserted into "
        f"'{COLLECTION_NAME}'."
    )


if __name__ == "__main__":
    asyncio.run(ingest())
