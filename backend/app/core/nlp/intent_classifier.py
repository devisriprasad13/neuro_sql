"""
Intent classifier for natural language queries.

Runs BEFORE SQL generation to determine:
    1. What SQL operation type the query requires
       (SELECT, INSERT, UPDATE, DELETE, DDL)
    2. Which tables are likely involved
    3. Whether the query spans multiple databases (federated)
    4. Confidence level of the classification

Why classify first?
    - Security: block unauthorized operations before LLM generation
    - Cost: avoid expensive SQL generation for blocked requests
    - Accuracy: tell the SQL generator exactly what type to produce

Uses GPT-4 with structured output — fast and cheap (~100 tokens).
The full SQL generation call costs ~500-2000 tokens.
Catching a blocked DELETE here saves ~1900 tokens per blocked request.

Operation types:
    READ   → SELECT queries, EXPLAIN
    INSERT → INSERT INTO
    UPDATE → UPDATE SET
    DELETE → DELETE FROM
    DDL    → CREATE, ALTER, DROP, TRUNCATE
"""

from enum import Enum

from pydantic import BaseModel, Field

from app.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class SQLOperationType(str, Enum):
    """
    The SQL operation type required to answer a natural language query.

    Using an Enum enforces that the LLM can only return one of these
    exact values — no hallucinated operation types.
    """
    READ   = "READ"    # SELECT queries
    INSERT = "INSERT"  # INSERT INTO
    UPDATE = "UPDATE"  # UPDATE SET
    DELETE = "DELETE"  # DELETE FROM
    DDL    = "DDL"     # CREATE, ALTER, DROP, TRUNCATE


class IntentClassification(BaseModel):
    """
    Structured output schema for intent classification.

    LangChain's with_structured_output enforces that GPT-4
    returns exactly this structure — no extra fields, no missing
    fields, correct types guaranteed.
    """

    operation_type: SQLOperationType = Field(
        description=(
            "The SQL operation type needed to answer this query. "
            "READ for SELECT, INSERT for adding data, UPDATE for modifying, "
            "DELETE for removing, DDL for schema changes."
        )
    )

    target_tables: list[str] = Field(
        default_factory=list,
        description=(
            "List of table names this query likely involves. "
            "Extract from the query context. Empty if cannot determine."
        )
    )

    is_federated: bool = Field(
        default=False,
        description=(
            "True if this query requires data from multiple databases. "
            "e.g. 'Compare sales from our CRM with revenue from our warehouse'"
        )
    )

    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Confidence score 0.0-1.0 for this classification. "
            "Use lower values when the query is ambiguous."
        )
    )

    reasoning: str = Field(
        default="",
        description=(
            "Brief explanation of why this operation type was chosen. "
            "Used for debugging and audit logging."
        )
    )


# ------------------------------------------------------------------ #
# System prompt for intent classification
#
# This prompt is carefully engineered to:
# 1. Be unambiguous about what each operation type means
# 2. Handle edge cases (ambiguous queries, multi-step requests)
# 3. Be fast — no chain-of-thought needed, just classification
# ------------------------------------------------------------------ #
INTENT_CLASSIFIER_SYSTEM_PROMPT = """You are a SQL intent classifier for NeuroSQL, an AI database management platform.

Your job is to analyze a natural language query and determine:
1. What SQL operation type it requires
2. Which database tables it likely involves
3. Whether it needs data from multiple databases

Operation type rules:
- READ: Any query asking to show, find, get, list, count, calculate, or analyze existing data
- INSERT: Any query asking to add, create, insert, or store new data
- UPDATE: Any query asking to modify, change, update, edit, or fix existing data
- DELETE: Any query asking to remove, delete, drop, or clear data rows
- DDL: Any query asking to create tables, alter schemas, or drop tables/columns

Important:
- "Show me sales data" → READ (viewing data)
- "Add a new customer" → INSERT (creating data)
- "Update the price of product X" → UPDATE (modifying data)
- "Delete orders from 2020" → DELETE (removing data)
- "Create a table for inventory" → DDL (schema change)
- Ambiguous queries that could be read or write → default to READ
- Always extract table names mentioned in the query

Be concise and accurate. This classification is used for security enforcement."""


class IntentClassifier:
    """
    Classifies natural language queries into SQL operation types.

    Uses GPT-4 with structured output for fast, reliable classification.
    The structured output constraint means GPT-4 cannot return anything
    outside the IntentClassification schema.

    Usage:
        classifier = IntentClassifier()
        result = await classifier.classify(
            "Show me total revenue by customer region"
        )
        print(result.operation_type)  # SQLOperationType.READ
        print(result.target_tables)   # ['orders', 'customers']
    """

    def __init__(self) -> None:
        from langchain_groq import ChatGroq
        base_llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0,
            api_key=settings.groq_api_key,
            max_tokens=500,
        )
        self.llm = base_llm.with_structured_output(IntentClassification)
    async def classify(self, query: str) -> IntentClassification:
        """
        Classify the SQL intent of a natural language query.

        Args:
            query: The user's natural language query.

        Returns:
            IntentClassification with operation type, tables, and confidence.

        Raises:
            Exception: If the OpenAI API call fails after retries.
                       Callers should handle this and return an error response.

        Example:
            result = await classifier.classify(
                "Delete all orders placed before January 2020"
            )
            # result.operation_type == SQLOperationType.DELETE
            # result.target_tables == ["orders"]
            # result.confidence == 0.95
        """
        logger.debug(
            "intent_classification_started",
            query=query[:100],
        )

        try:
            # Build the messages
            messages = [
                ("system", INTENT_CLASSIFIER_SYSTEM_PROMPT),
                ("human", f"Classify this query: {query}"),
            ]

            # Invoke the structured output LLM
            result: IntentClassification = await self.llm.ainvoke(messages)

            logger.info(
                "intent_classified",
                query=query[:100],
                operation_type=result.operation_type.value,
                target_tables=result.target_tables,
                is_federated=result.is_federated,
                confidence=result.confidence,
            )

            return result

        except Exception as e:
            logger.error(
                "intent_classification_failed",
                query=query[:100],
                error=str(e),
            )
            raise

    async def is_read_only(self, query: str) -> bool:
        """
        Quick check: does this query only need a SELECT?

        Convenience method for simple read-only validation.
        Cheaper than full classification when you only need
        to know if a query is safe to run without RBAC checks.

        Returns:
            True if the query is a READ operation.
        """
        result = await self.classify(query)
        return result.operation_type == SQLOperationType.READ