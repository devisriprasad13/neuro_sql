"""
SQL generator — converts natural language to SQL using LangChain + GPT-4.

Takes a natural language query, schema context from Pinecone RAG,
and the classified operation type, then generates valid SQL.

Architecture:
    NL query + schema context + operation type
        ↓ ChatPromptTemplate
    Formatted prompt with injected schema
        ↓ GPT-4o (via LangChain)
    Raw SQL string
        ↓ SQLOutputParser
    Clean SQL ready for validation

Key design decisions:
    1. Schema context injection: LLM only sees retrieved columns,
       not the full schema. Prevents hallucination of non-existent tables.

    2. Operation type constraint: System prompt tells LLM exactly
       which SQL type to generate. Prevents intent mismatch attacks.

    3. Dialect awareness: Different SQL syntax per database type.
       PostgreSQL uses RETURNING, MySQL uses LIMIT differently, etc.

    4. No markdown: Output parser strips code fences so SQL is
       ready for direct execution without post-processing.

    5. Temperature=0: Deterministic output. Same query + schema
       should always produce the same SQL. Critical for debugging.
"""

import re

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.config import get_settings
from app.core.nlp.intent_classifier import SQLOperationType
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


# ------------------------------------------------------------------ #
# SQL dialect hints
#
# Different databases have different syntax for common operations.
# These hints are injected into the system prompt based on db_type.
# ------------------------------------------------------------------ #
DIALECT_HINTS = {
    "postgres": """PostgreSQL dialect rules:
- Use $1, $2 placeholders for parameters (not ? or :name)
- Use RETURNING clause for INSERT/UPDATE/DELETE when returning data
- Use ILIKE for case-insensitive string matching
- Use NOW() for current timestamp
- UUID columns use uuid type
- Use LIMIT/OFFSET for pagination""",

    "mysql": """MySQL dialect rules:
- Use %s placeholders for parameters
- Use LIMIT for pagination
- Use IFNULL() instead of COALESCE() for simple cases
- Use CONCAT() for string concatenation
- Use NOW() for current timestamp
- Use BACKTICK quoting for reserved word column names""",

    "bigquery": """BigQuery dialect rules:
- Use @param_name for named parameters
- Use LIMIT for pagination
- Use SAFE_CAST() for safe type casting
- Use FORMAT_TIMESTAMP() for timestamp formatting
- Use CURRENT_TIMESTAMP() for current time
- Use backtick quoting for table/column names""",

    "snowflake": """Snowflake dialect rules:
- Use :param_name or ? for parameters
- Use LIMIT/OFFSET for pagination
- Use IFF() for simple conditionals
- Use CURRENT_TIMESTAMP() for current time
- Use :: for type casting (e.g. value::VARCHAR)""",
}

# ------------------------------------------------------------------ #
# Operation type instructions
#
# Injected into the prompt to constrain SQL generation to the
# permitted operation type. Prevents the LLM from generating
# a DELETE when the user asked for a SELECT.
# ------------------------------------------------------------------ #
OPERATION_INSTRUCTIONS = {
    SQLOperationType.READ: (
        "Generate ONLY a SELECT statement. "
        "Do not generate INSERT, UPDATE, DELETE, or DDL. "
        "Use appropriate JOINs, WHERE clauses, GROUP BY, and ORDER BY as needed."
    ),
    SQLOperationType.INSERT: (
        "Generate ONLY an INSERT INTO statement. "
        "Include all required non-nullable columns. "
        "Use parameter placeholders for all values — never hardcode user data."
    ),
    SQLOperationType.UPDATE: (
        "Generate ONLY an UPDATE statement. "
        "Always include a WHERE clause to avoid updating all rows. "
        "Use parameter placeholders for all values."
    ),
    SQLOperationType.DELETE: (
        "Generate ONLY a DELETE FROM statement. "
        "Always include a WHERE clause. "
        "Never generate DELETE without a WHERE clause."
    ),
    SQLOperationType.DDL: (
        "Generate ONLY DDL statements (CREATE TABLE, ALTER TABLE). "
        "Do not generate DROP or TRUNCATE unless explicitly requested. "
        "Use IF NOT EXISTS for CREATE statements."
    ),
}

# ------------------------------------------------------------------ #
# Main system prompt template
# ------------------------------------------------------------------ #
SYSTEM_PROMPT_TEMPLATE = """You are an expert SQL generator for NeuroSQL.
Your job is to convert natural language queries into valid SQL.

CRITICAL RULES:
1. Generate ONLY SQL — no explanations, no markdown, no code fences
2. Only use tables and columns from the provided schema context
3. Never reference tables or columns not shown in the schema
4. {operation_instruction}

DATABASE: {db_type}
{dialect_hint}

SCHEMA CONTEXT (use ONLY these tables and columns):
{schema_context}

OUTPUT FORMAT:
- Return the SQL statement only
- No backticks, no ```sql fences, no explanations
- End with a semicolon"""

HUMAN_PROMPT_TEMPLATE = "Convert this to SQL: {query}"


class SQLOutputParser(StrOutputParser):
    """
    Custom output parser that cleans LLM-generated SQL.

    Strips common artifacts from LLM output:
    - Markdown code fences (```sql ... ```)
    - Leading/trailing whitespace
    - Explanatory text before/after the SQL

    Inherits from StrOutputParser for LangChain chain compatibility.
    """

    def parse(self, text: str) -> str:
        """Clean the raw LLM output to extract pure SQL."""
        # Remove markdown code fences
        text = re.sub(r"```sql\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"```\s*", "", text)

        # Remove common preamble phrases LLMs add
        preambles = [
            r"^here is the sql.*?:\s*",
            r"^here's the sql.*?:\s*",
            r"^the sql query.*?:\s*",
            r"^sql:\s*",
        ]
        for pattern in preambles:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Strip whitespace and normalize
        text = text.strip()

        # Ensure statement ends with semicolon
        if text and not text.endswith(";"):
            text += ";"

        return text


class SQLGenerator:
    """
    Generates SQL from natural language using LangChain + GPT-4o.

    Usage:
        generator = SQLGenerator()

        sql = await generator.generate(
            query="Show me total revenue by customer region",
            schema_context=retrieved_schema_string,
            operation_type=SQLOperationType.READ,
            db_type="postgres",
        )
        print(sql)
        # SELECT region, SUM(total_amount) as revenue
        # FROM orders o JOIN customers c ON o.customer_id = c.id
        # GROUP BY region ORDER BY revenue DESC;
    """

    def __init__(self) -> None:
        from langchain_groq import ChatGroq
        self.llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0,
            api_key=settings.groq_api_key,
            max_tokens=2000,
        )
        self.output_parser = SQLOutputParser()

    async def generate(
        self,
        query: str,
        schema_context: str,
        operation_type: SQLOperationType,
        db_type: str = "postgres",
    ) -> str:
        """
        Generate SQL from a natural language query.

        Args:
            query:          User's natural language query.
            schema_context: Formatted schema string from SchemaRetriever.
                           Contains only the relevant tables and columns.
            operation_type: Classified operation type from IntentClassifier.
                           Constrains what SQL the generator can produce.
            db_type:        Target database dialect. Affects SQL syntax.

        Returns:
            Clean SQL string ready for validation and execution.

        Raises:
            Exception: If OpenAI API fails or output cannot be parsed.

        Example:
            sql = await generator.generate(
                query="List all active users",
                schema_context="Table: users\\n  - id: uuid | PRIMARY KEY\\n  - email: varchar\\n  - is_active: boolean",
                operation_type=SQLOperationType.READ,
                db_type="postgres",
            )
        """
        logger.info(
            "sql_generation_started",
            query=query[:100],
            operation_type=operation_type.value,
            db_type=db_type,
        )

        # Get dialect-specific hints
        dialect_hint = DIALECT_HINTS.get(
            db_type.lower(),
            f"Use standard SQL syntax for {db_type}."
        )

        # Get operation-specific instruction
        operation_instruction = OPERATION_INSTRUCTIONS.get(
            operation_type,
            "Generate appropriate SQL for this query."
        )

        # Build the prompt template
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT_TEMPLATE),
            ("human", HUMAN_PROMPT_TEMPLATE),
        ])

        # Build the chain: prompt → LLM → output parser
        chain = prompt | self.llm | self.output_parser

        try:
            sql = await chain.ainvoke({
                "operation_instruction": operation_instruction,
                "db_type": db_type.upper(),
                "dialect_hint": dialect_hint,
                "schema_context": schema_context,
                "query": query,
            })

            logger.info(
                "sql_generation_completed",
                query=query[:100],
                sql_preview=sql[:100],
                sql_length=len(sql),
            )

            return sql

        except Exception as e:
            logger.error(
                "sql_generation_failed",
                query=query[:100],
                error=str(e),
            )
            raise

    async def generate_with_error_context(
        self,
        query: str,
        schema_context: str,
        operation_type: SQLOperationType,
        db_type: str,
        previous_sql: str,
        error_message: str,
    ) -> str:
        """
        Regenerate SQL using the previous attempt's error as context.

        Called by the self-correction engine when validation fails.
        The error message is injected so the LLM knows what went wrong.

        Args:
            query:           Original natural language query.
            schema_context:  Same schema context as the first attempt.
            operation_type:  Same operation type as the first attempt.
            db_type:         Target database dialect.
            previous_sql:    The SQL that failed validation.
            error_message:   The specific error from the validator.

        Returns:
            Corrected SQL string.
        """
        logger.info(
            "sql_correction_generation_started",
            query=query[:100],
            error=error_message[:100],
        )

        dialect_hint = DIALECT_HINTS.get(db_type.lower(), "")
        operation_instruction = OPERATION_INSTRUCTIONS.get(
            operation_type,
            "Generate appropriate SQL."
        )

        correction_system_prompt = SYSTEM_PROMPT_TEMPLATE + """

CORRECTION CONTEXT:
Your previous SQL attempt failed with this error:
Error: {error_message}

Failed SQL:
{previous_sql}

Fix the SQL to resolve this error while keeping the same intent."""

        prompt = ChatPromptTemplate.from_messages([
            ("system", correction_system_prompt),
            ("human", HUMAN_PROMPT_TEMPLATE),
        ])

        chain = prompt | self.llm | self.output_parser

        try:
            sql = await chain.ainvoke({
                "operation_instruction": operation_instruction,
                "db_type": db_type.upper(),
                "dialect_hint": dialect_hint,
                "schema_context": schema_context,
                "query": query,
                "error_message": error_message,
                "previous_sql": previous_sql,
            })

            logger.info(
                "sql_correction_generation_completed",
                sql_preview=sql[:100],
            )

            return sql

        except Exception as e:
            logger.error(
                "sql_correction_generation_failed",
                error=str(e),
            )
            raise