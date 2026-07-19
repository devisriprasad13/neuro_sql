"""
Database connectors package.

Public API — import from here, not from individual connector modules:

    from app.connectors import get_connector, ConnectionConfig, QueryResult

The get_connector() factory returns the correct connector
for a given database type without the caller knowing which
specific class is being used.
"""

from app.connectors.base import (
    BaseConnector,
    ConnectionConfig,
    QueryResult,
    TableMetadata,
    get_connector,
)

__all__ = [
    "BaseConnector",
    "ConnectionConfig",
    "QueryResult",
    "TableMetadata",
    "get_connector",
]