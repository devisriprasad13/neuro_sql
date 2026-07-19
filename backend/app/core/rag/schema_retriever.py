"""
Schema retriever — query-time RAG component.

Retrieves relevant schema context from Pinecone given a natural
language query. The retrieved schema is injected into the LLM
prompt to prevent hallucinated column names and table references.

Flow:
    User NL query
        ↓ SchemaRetriever.retrieve()
    Pinecone similarity search (hosted llama-text-embed-v2)
        ↓
    Top-k schema columns (raw results)
        ↓ format_schema_context()
    Structured schema string for LLM prompt injection
        ↓
    LLM generates SQL using only these columns

Why top_k=15?
    Too few (5): LLM misses JOIN columns, WHERE conditions
    Too many (30+): LLM prompt grows, hallucination risk increases,
                    cost per query increases
    15 is the empirically good balance for most queries.
    Complex federated queries may need top_k=25.

Performance:
    Pinecone similarity search: ~10-30ms
    Total retriever overhead: ~15-40ms
    This is negligible vs LLM generation time (~2-5 seconds)
"""

import uuid
from collections import defaultdict

from app.core.rag.schema_embedder import SchemaEmbedder
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SchemaRetriever:
    """
    Retrieves and formats schema context for LLM prompt injection.

    Usage:
        retriever = SchemaRetriever()

        # Get formatted schema context for a query
        context = await retriever.retrieve(
            query="show me total revenue by customer region",
            connection_ids=[uuid1, uuid2],
            top_k=15,
        )
        # context is a string ready to inject into the LLM system prompt
    """

    def __init__(self) -> None:
        self.embedder = SchemaEmbedder()

    async def retrieve(
        self,
        query: str,
        connection_ids: list[uuid.UUID],
        top_k: int = 15,
    ) -> str:
        """
        Retrieve relevant schema context for a natural language query.

        Args:
            query:          User's natural language query.
            connection_ids: Database connections to search schema from.
            top_k:          Number of schema columns to retrieve.

        Returns:
            Formatted schema context string for LLM prompt injection.
            Returns empty string if no results found.

        Example return value:
            '''
            Available database schema:

            Table: orders (connection: sales_db)
              - order_id: integer | PRIMARY KEY | not nullable
              - customer_id: integer | FOREIGN KEY → customers.id | not nullable
              - total_amount: numeric | not nullable
              - status: character varying | not nullable
              - created_at: timestamp with time zone | not nullable

            Table: customers (connection: sales_db)
              - id: integer | PRIMARY KEY | not nullable
              - name: character varying | not nullable
              - region: character varying | nullable
            '''
        """
        if not query.strip():
            logger.warning("schema_retrieval_empty_query")
            return ""

        if not connection_ids:
            logger.warning("schema_retrieval_no_connections")
            return ""

        # Retrieve raw schema matches from Pinecone
        matches = await self.embedder.search_schema(
            query=query,
            connection_ids=connection_ids,
            top_k=top_k,
        )

        if not matches:
            logger.warning(
                "schema_retrieval_no_matches",
                query=query[:50],
            )
            return ""

        logger.debug(
            "schema_retrieval_matches_found",
            query=query[:50],
            match_count=len(matches),
            top_score=matches[0]["score"] if matches else 0,
        )

        # Format matches into structured context string
        return self.format_schema_context(matches)

    def format_schema_context(self, matches: list[dict]) -> str:
        """
        Format raw Pinecone matches into a structured schema context string.

        Groups columns by table name and formats them in a way that
        is clear and unambiguous for the LLM to use when generating SQL.

        The format is designed to:
        1. Be easy for the LLM to parse
        2. Include all information needed for correct SQL generation
        3. Show relationships (FK references) explicitly
        4. Group columns by table to make JOIN logic obvious

        Args:
            matches: List of schema match dicts from SchemaEmbedder.search_schema()

        Returns:
            Formatted multi-line string with schema context.
        """
        if not matches:
            return ""

        # Group columns by (connection_id, table_name)
        # This groups related columns together for cleaner output
        tables: dict[tuple, list[dict]] = defaultdict(list)

        for match in matches:
            key = (match["connection_id"], match["table_name"])
            tables[key].append(match)

        # Sort tables by relevance score of their best column match
        # Tables with more relevant columns appear first
        def table_best_score(item):
            _, columns = item
            return max(col["score"] for col in columns)

        sorted_tables = sorted(
            tables.items(),
            key=table_best_score,
            reverse=True,
        )

        # Build the formatted context string
        lines = ["Available database schema:\n"]

        for (connection_id, table_name), columns in sorted_tables:
            # Table header
            lines.append(f"Table: {table_name}")

            # Sort columns: primary keys first, then foreign keys, then rest
            def column_sort_key(col):
                if col["is_primary_key"]:
                    return 0
                if col["is_foreign_key"]:
                    return 1
                return 2

            sorted_columns = sorted(columns, key=column_sort_key)

            for col in sorted_columns:
                col_parts = [
                    f"  - {col['column_name']}: {col['data_type'] or 'unknown'}",
                ]

                if col["is_primary_key"]:
                    col_parts.append("PRIMARY KEY")

                if col["is_foreign_key"] and col["fk_references"]:
                    col_parts.append(f"FOREIGN KEY → {col['fk_references']}")
                elif col["is_foreign_key"]:
                    col_parts.append("FOREIGN KEY")

                nullable_text = "nullable" if not col.get("is_primary_key") else "not nullable"
                col_parts.append(nullable_text)

                lines.append(" | ".join(col_parts))

            lines.append("")  # Blank line between tables

        return "\n".join(lines)

    async def retrieve_raw(
        self,
        query: str,
        connection_ids: list[uuid.UUID],
        top_k: int = 15,
    ) -> list[dict]:
        """
        Retrieve raw schema matches without formatting.

        Used when the caller needs the structured data rather
        than the formatted string — e.g. for intent classification
        or when building custom prompt formats.

        Args:
            query:          User's natural language query.
            connection_ids: Database connections to search.
            top_k:          Number of results to retrieve.

        Returns:
            Raw list of schema match dicts from Pinecone.
        """
        return await self.embedder.search_schema(
            query=query,
            connection_ids=connection_ids,
            top_k=top_k,
        )

    def extract_table_names(self, matches: list[dict]) -> list[str]:
        """
        Extract unique table names from schema matches.

        Used by the SQL validator to verify that generated SQL
        only references tables that exist in the retrieved schema.

        Args:
            matches: Raw schema match dicts.

        Returns:
            Sorted list of unique table names.
        """
        table_names = {match["table_name"] for match in matches}
        return sorted(table_names)

    def extract_column_names(
        self, matches: list[dict], table_name: str | None = None
    ) -> list[str]:
        """
        Extract column names from schema matches.

        Args:
            matches:    Raw schema match dicts.
            table_name: If provided, only return columns for this table.

        Returns:
            Sorted list of unique column names.
        """
        if table_name:
            columns = {
                match["column_name"]
                for match in matches
                if match["table_name"] == table_name
            }
        else:
            columns = {match["column_name"] for match in matches}

        return sorted(columns)