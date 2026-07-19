"""
Pytest configuration for NeuroSQL test suite.

Configures:
    - asyncio mode for async test functions
    - shared fixtures available to all test modules
"""

import pytest


# Configure pytest-asyncio to auto-detect async test functions
# This means @pytest.mark.asyncio is applied automatically
# to all async def test_* functions
def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as async"
    )