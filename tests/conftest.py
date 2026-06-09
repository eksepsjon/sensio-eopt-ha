"""
Pytest configuration for sensio-eopt-control tests.

pytest-homeassistant-custom-component installs pytest-socket which blocks all
socket creation by default (to prevent tests making real network connections).
On Windows this also blocks asyncio's internal socket pair.

We override the event loop to use the stdlib SelectorEventLoop (via a plain
asyncio policy) instead of HA's ProactorEventLoop-based policy, which avoids
the Windows socket-pair issue in non-HA tests.
"""

import asyncio
import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use the default asyncio policy (SelectorEventLoop on non-Windows,
    compatible loop on Windows) instead of HA's custom policy."""
    return asyncio.DefaultEventLoopPolicy()
