"""
Self-correction engine.

Orchestrates the full SQL generation → validation → correction loop.

Flow:
    1. Generate SQL (SQLGenerator)
    2. Validate syntax (SyntaxValidator)      — Stage 1
    3. Check hallucinations (HallucinationChecker) — Stage 2
    4. Dry-run EXPLAIN (DryRunValidator)      — Stage 3
    5. If any stage fails → regenerate with error context
    6. Repeat up to MAX_ATTEMPTS times
    7. Return final result (success or failure)

Why 3 attempts maximum?
    Research shows 85%+ of fixable errors resolve within 2 retries.
    Attempt 3 catches most of the remainder.
    Beyond 3: error probability <5%, cost exceeds benefit.
    Queries failing 3 times need schema fix or query rephrasing.

Cost analysis per query:
    Attempt 1: ~500 tokens (generation)
    Attempt 2: ~700 tokens (generation + error context)
    Attempt 3: ~900 tokens (generation + 2 error contexts)
    Max cost: ~2100 tokens per query with correction
    vs ~500 tokens for queries that pass first time
"""

import time
from dataclasses import dataclass, field

from app.connectors.base import ConnectionConfig
from app.core.nlp.intent_classifier import SQLOperationType
from app.core.nlp.sql_generator import SQLGenerator
from app.core.validation.dry_run_validator import DryRunValidator
from app.core.validation.hallucination_checker import HallucinationChecker
from app.core.validation.syntax_validator import SyntaxValidator
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_ATTEMPTS = 3


@dataclass
class ValidationError:
    """A single validation failure with stage and message."""
    stage: str         # 'syntax' | 'hallucination' | 'dry_run'
    message: str
    attempt: int


@dataclass
class CorrectionResult:
    """
    Final result of the self-correction loop.

    Attributes:
        success:            True if valid SQL was produced.
        final_sql:          The validated SQL (or last attempt if failed).
        attempts:           How many generation attempts were made.
        was_corrected:      True if correction was needed (attempts > 1).
        errors:             List of validation errors encountered.
        total_time_ms:      Total time for all attempts.
        final_error:        Error message if all attempts failed.
    """
    success: bool
    final_sql: str
    attempts: int
    was_corrected: bool
    errors: list[ValidationError] = field(default_factory=list)
    total_time_ms: float = 0.0
    final_error: str | None = None


class SelfCorrectionEngine:
    """
    Orchestrates SQL generation, validation, and self-correction.

    Usage:
        engine = SelfCorrectionEngine()
        result = await engine.generate_and_validate(
            query="Show me all active users",
            schema_context=retrieved_schema,
            schema_matches=raw_pinecone_matches,
            operation_type=SQLOperationType.READ,
            db_type="postgres",
            connection_config=config,  # optional, for Stage 3
        )
        if result.success:
            print(result.final_sql)
        else:
            print(f"Failed after {result.attempts} attempts: {result.final_error}")
    """

    def __init__(self) -> None:
        self.generator = SQLGenerator()
        self.syntax_validator = SyntaxValidator()
        self.hallucination_checker = HallucinationChecker()
        self.dry_run_validator = DryRunValidator()

    async def generate_and_validate(
        self,
        query: str,
        schema_context: str,
        schema_matches: list[dict],
        operation_type: SQLOperationType,
        db_type: str = "postgres",
        connection_config: ConnectionConfig | None = None,
        skip_dry_run: bool = False,
    ) -> CorrectionResult:
        """
        Generate SQL and validate it, retrying with error context on failure.

        Args:
            query:             User's natural language query.
            schema_context:    Formatted schema string for LLM prompt.
            schema_matches:    Raw Pinecone matches for hallucination check.
            operation_type:    Classified SQL operation type.
            db_type:           Target database dialect.
            connection_config: Target DB config for Stage 3 dry-run.
                              If None, Stage 3 is skipped.
            skip_dry_run:      If True, skip Stage 3 (useful for testing).

        Returns:
            CorrectionResult with final SQL and attempt metadata.
        """
        start_time = time.monotonic()
        errors: list[ValidationError] = []
        current_sql = ""
        previous_error = None

        logger.info(
            "self_correction_started",
            query=query[:100],
            operation_type=operation_type.value,
            db_type=db_type,
            max_attempts=MAX_ATTEMPTS,
        )

        for attempt in range(1, MAX_ATTEMPTS + 1):
            logger.debug(
                "generation_attempt",
                attempt=attempt,
                has_previous_error=previous_error is not None,
            )

            # -------------------------------------------------------- #
            # Generate SQL
            # -------------------------------------------------------- #
            try:
                if attempt == 1 or previous_error is None:
                    # First attempt — standard generation
                    current_sql = await self.generator.generate(
                        query=query,
                        schema_context=schema_context,
                        operation_type=operation_type,
                        db_type=db_type,
                    )
                else:
                    # Subsequent attempts — include error context
                    current_sql = await self.generator.generate_with_error_context(
                        query=query,
                        schema_context=schema_context,
                        operation_type=operation_type,
                        db_type=db_type,
                        previous_sql=current_sql,
                        error_message=previous_error,
                    )
            except Exception as e:
                logger.error(
                    "generation_failed",
                    attempt=attempt,
                    error=str(e),
                )
                total_time = (time.monotonic() - start_time) * 1000
                return CorrectionResult(
                    success=False,
                    final_sql=current_sql,
                    attempts=attempt,
                    was_corrected=attempt > 1,
                    errors=errors,
                    total_time_ms=round(total_time, 2),
                    final_error=f"SQL generation failed: {str(e)}",
                )

            # -------------------------------------------------------- #
            # Stage 1: Syntax validation
            # -------------------------------------------------------- #
            syntax_result = self.syntax_validator.validate(current_sql, db_type)
            if not syntax_result.is_valid:
                error = ValidationError(
                    stage="syntax",
                    message=syntax_result.error or "Syntax validation failed",
                    attempt=attempt,
                )
                errors.append(error)
                previous_error = error.message
                logger.warning(
                    "syntax_validation_failed",
                    attempt=attempt,
                    error=error.message,
                )
                if attempt < MAX_ATTEMPTS:
                    continue
                else:
                    break

            # -------------------------------------------------------- #
            # Stage 2: Hallucination check
            # -------------------------------------------------------- #
            hallucination_result = self.hallucination_checker.check(
                sql=current_sql,
                schema_matches=schema_matches,
                db_type=db_type,
                strict_mode=False,
            )
            if not hallucination_result.is_valid:
                error = ValidationError(
                    stage="hallucination",
                    message=hallucination_result.error or "Hallucination detected",
                    attempt=attempt,
                )
                errors.append(error)
                previous_error = error.message
                logger.warning(
                    "hallucination_check_failed",
                    attempt=attempt,
                    hallucinated_tables=hallucination_result.hallucinated_tables,
                    hallucinated_columns=hallucination_result.hallucinated_columns,
                )
                if attempt < MAX_ATTEMPTS:
                    continue
                else:
                    break

            # -------------------------------------------------------- #
            # Stage 3: Dry-run EXPLAIN (optional)
            # -------------------------------------------------------- #
            if not skip_dry_run and connection_config:
                dry_run_result = await self.dry_run_validator.validate(
                    sql=current_sql,
                    connection_config=connection_config,
                )
                if not dry_run_result.is_valid and not dry_run_result.skipped:
                    error = ValidationError(
                        stage="dry_run",
                        message=dry_run_result.error or "EXPLAIN validation failed",
                        attempt=attempt,
                    )
                    errors.append(error)
                    previous_error = error.message
                    logger.warning(
                        "dry_run_failed",
                        attempt=attempt,
                        error=error.message,
                    )
                    if attempt < MAX_ATTEMPTS:
                        continue
                    else:
                        break

            # -------------------------------------------------------- #
            # All stages passed — success
            # -------------------------------------------------------- #
            total_time = (time.monotonic() - start_time) * 1000
            was_corrected = attempt > 1

            logger.info(
                "self_correction_succeeded",
                query=query[:100],
                attempts=attempt,
                was_corrected=was_corrected,
                total_time_ms=round(total_time, 2),
            )

            return CorrectionResult(
                success=True,
                final_sql=current_sql,
                attempts=attempt,
                was_corrected=was_corrected,
                errors=errors,
                total_time_ms=round(total_time, 2),
            )

        # ------------------------------------------------------------ #
        # All attempts exhausted — return failure
        # ------------------------------------------------------------ #
        total_time = (time.monotonic() - start_time) * 1000
        final_error = errors[-1].message if errors else "Unknown validation failure"

        logger.error(
            "self_correction_failed",
            query=query[:100],
            attempts=MAX_ATTEMPTS,
            final_error=final_error,
            total_time_ms=round(total_time, 2),
        )

        return CorrectionResult(
            success=False,
            final_sql=current_sql,
            attempts=MAX_ATTEMPTS,
            was_corrected=True,
            errors=errors,
            total_time_ms=round(total_time, 2),
            final_error=final_error,
        )