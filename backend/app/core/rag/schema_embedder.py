"""
Schema embedder — indexes schema metadata into Pinecone.

Converts database schema snapshots into semantic vector embeddings
and stores them in Pinecone for RAG-based retrieval during SQL generation.

Architecture:
    SchemaSnapshot rows (Postgres)
        ↓ build_embedding_text()
    Rich text descriptions
        ↓ Pinecone upsert with hosted llama-text-embed-v2
    Vectors in Pinecone index "neurosql"
        ↓ query time: embed NL query → similarity search
    Top-k relevant schema columns → injected into LLM prompt
"""

import uuid

from pinecone import Pinecone

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

SCHEMA_NAMESPACE = "schema"
UPSERT_BATCH_SIZE = 90


def get_pinecone_index():
    """Initialize and return the Pinecone index client."""
    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index_name)
    return index


def build_embedding_text(
    table_name: str,
    table_schema: str,
    column_name: str,
    data_type: str | None,
    is_nullable: bool,
    is_primary_key: bool,
    is_foreign_key: bool,
    fk_references: str | None,
) -> str:
    """
    Build a rich semantic text description of a database column.

    This text is embedded into a vector for RAG retrieval.
    """
    parts = [
        f"{table_name} table",
        f"{column_name} column",
    ]

    if data_type:
        parts.append(f"{data_type} type")

    if is_primary_key:
        parts.append("primary key")

    if is_foreign_key and fk_references:
        parts.append(f"foreign key references {fk_references}")
    elif is_foreign_key:
        parts.append("foreign key")

    parts.append("nullable" if is_nullable else "not nullable")

    if table_schema and table_schema != "public":
        parts.append(f"schema {table_schema}")

    return ", ".join(parts)


class SchemaEmbedder:
    """
    Embeds schema metadata into Pinecone using hosted embeddings.

    Usage:
        embedder = SchemaEmbedder()
        result = await embedder.embed_connection_schema(
            connection_id=uuid,
            org_id=uuid,
            snapshots=list_of_snapshot_dicts,
        )
        matches = await embedder.search_schema(
            query="show me total revenue by customer",
            connection_ids=[uuid1],
            top_k=15,
        )
    """

    def __init__(self) -> None:
        self.index = get_pinecone_index()

    async def embed_connection_schema(
        self,
        connection_id: uuid.UUID,
        org_id: uuid.UUID,
        snapshots: list[dict],
    ) -> dict:
        """
        Embed all schema snapshots for one database connection.

        Deletes existing vectors first, then upserts fresh vectors.
        """
        logger.info(
            "schema_embedding_started",
            connection_id=str(connection_id),
            snapshot_count=len(snapshots),
        )

        try:
            deleted_count = await self._delete_connection_vectors(connection_id)

            records = []
            for snapshot in snapshots:
                text = build_embedding_text(
                    table_name=snapshot["table_name"],
                    table_schema=snapshot.get("table_schema", "public"),
                    column_name=snapshot["column_name"],
                    data_type=snapshot.get("data_type"),
                    is_nullable=snapshot.get("is_nullable", True),
                    is_primary_key=snapshot.get("is_primary_key", False),
                    is_foreign_key=snapshot.get("is_foreign_key", False),
                    fk_references=snapshot.get("fk_references"),
                )

                vector_id = (
                    f"{connection_id}_"
                    f"{snapshot['table_name']}_"
                    f"{snapshot['column_name']}"
                )

                records.append({
                    "id": vector_id,
                    "text": text,
                    "metadata": {
                        "connection_id": str(connection_id),
                        "org_id": str(org_id),
                        "table_name": snapshot["table_name"],
                        "table_schema": snapshot.get("table_schema", "public"),
                        "column_name": snapshot["column_name"],
                        "data_type": snapshot.get("data_type", "unknown"),
                        "is_primary_key": snapshot.get("is_primary_key", False),
                        "is_foreign_key": snapshot.get("is_foreign_key", False),
                        "fk_references": snapshot.get("fk_references") or "",
                        "snapshot_id": str(snapshot.get("snapshot_id", "")),
                        "embedding_text": text,
                    },
                })

            embedded_count = await self._upsert_in_batches(records)

            logger.info(
                "schema_embedding_completed",
                connection_id=str(connection_id),
                embedded_count=embedded_count,
                deleted_count=deleted_count,
            )

            return {
                "embedded_count": embedded_count,
                "deleted_count": deleted_count,
                "status": "success",
                "error": None,
            }

        except Exception as e:
            logger.error(
                "schema_embedding_failed",
                connection_id=str(connection_id),
                error=str(e),
            )
            return {
                "embedded_count": 0,
                "deleted_count": 0,
                "status": "failed",
                "error": str(e),
            }

    async def search_schema(
        self,
        query: str,
        connection_ids: list[uuid.UUID],
        top_k: int = 15,
    ) -> list[dict]:
        """
        Search for schema columns relevant to a natural language query.
        """
        if not connection_ids:
            logger.warning("schema_search_no_connections")
            return []

        try:
            connection_id_strings = [str(cid) for cid in connection_ids]

            # Search without filter — Pinecone hosted search doesn't
            # support metadata filtering with search_records in v6
            # We retrieve more results and filter client-side
            response = self.index.search_records(
                namespace=SCHEMA_NAMESPACE,
                query={
                    "inputs": {"text": query},
                    "top_k": top_k * 3,  # retrieve 3x to account for filtering
                },
                fields=[
                    "connection_id", "org_id", "table_name", "table_schema",
                    "column_name", "data_type", "is_primary_key",
                    "is_foreign_key", "fk_references", "embedding_text",
                ],
            )

            results = []
            hits = response.get("result", {}).get("hits", [])

            for hit in hits:
                fields = hit.get("fields", {})
                hit_connection_id = fields.get("connection_id", "")

                # Client-side filter by connection_id
                if hit_connection_id not in connection_id_strings:
                    continue

                results.append({
                    "score": hit.get("_score", 0.0),
                    "table_name": fields.get("table_name", ""),
                    "column_name": fields.get("column_name", ""),
                    "data_type": fields.get("data_type", ""),
                    "is_primary_key": fields.get("is_primary_key", False),
                    "is_foreign_key": fields.get("is_foreign_key", False),
                    "fk_references": fields.get("fk_references", ""),
                    "connection_id": fields.get("connection_id", ""),
                    "table_schema": fields.get("table_schema", "public"),
                    "embedding_text": fields.get("embedding_text", ""),
                })

                # Stop once we have enough results
                if len(results) >= top_k:
                    break

            logger.debug(
                "schema_search_completed",
                query=query[:50],
                result_count=len(results),
            )

            return results

        except Exception as e:
            logger.error(
                "schema_search_failed",
                query=query[:50],
                error=str(e),
            )
            return []

    async def _delete_connection_vectors(
        self, connection_id: uuid.UUID
    ) -> int:
        """Delete all vectors for a specific connection from Pinecone."""
        try:
            self.index.delete(
                namespace=SCHEMA_NAMESPACE,
                filter={"connection_id": {"$eq": str(connection_id)}},
            )
            logger.debug(
                "pinecone_vectors_deleted",
                connection_id=str(connection_id),
            )
            return 0
        except Exception as e:
            error_str = str(e)
            if "Namespace not found" in error_str or "404" in error_str:
                logger.debug(
                    "pinecone_namespace_not_found_on_delete",
                    connection_id=str(connection_id),
                )
            else:
                logger.warning(
                    "pinecone_delete_failed",
                    connection_id=str(connection_id),
                    error=error_str,
                )
            return 0

    async def _upsert_in_batches(self, records: list[dict]) -> int:
        """
        Upsert vectors into Pinecone in batches.

        Pinecone upsert_records requires flat metadata fields —
        strings, numbers, booleans, or lists of strings only.
        No nested dicts allowed.
        """
        total_upserted = 0

        for i in range(0, len(records), UPSERT_BATCH_SIZE):
            batch = records[i:i + UPSERT_BATCH_SIZE]

            pinecone_records = []
            for record in batch:
                meta = record["metadata"]
                pinecone_records.append({
                    "_id": record["id"],
                    "text": record["text"],
                    "connection_id": meta["connection_id"],
                    "org_id": meta["org_id"],
                    "table_name": meta["table_name"],
                    "table_schema": meta["table_schema"],
                    "column_name": meta["column_name"],
                    "data_type": meta["data_type"],
                    "is_primary_key": meta["is_primary_key"],
                    "is_foreign_key": meta["is_foreign_key"],
                    "fk_references": meta.get("fk_references") or "",
                    "snapshot_id": meta["snapshot_id"],
                    "embedding_text": meta["embedding_text"],
                })

            try:
                self.index.upsert_records(
                    namespace=SCHEMA_NAMESPACE,
                    records=pinecone_records,
                )
                total_upserted += len(batch)
                logger.debug(
                    "pinecone_batch_upserted",
                    batch_size=len(batch),
                    total_so_far=total_upserted,
                )
            except Exception as e:
                logger.error(
                    "pinecone_batch_upsert_failed",
                    batch_index=i // UPSERT_BATCH_SIZE,
                    error=str(e),
                )
                raise

        return total_upserted