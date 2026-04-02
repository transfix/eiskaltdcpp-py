"""
Shared pytest configuration for eiskaltdcpp-py tests.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

import bcrypt
import pytest


def pytest_runtest_logreport(report):
    """Print failure/error details immediately so they appear in CI logs
    even if the process crashes before the summary section."""
    if report.when in ("call", "setup") and report.failed:
        print(f"\n{'='*60}", file=sys.stderr, flush=True)
        print(f"IMMEDIATE FAIL: {report.nodeid}", file=sys.stderr, flush=True)
        print(report.longreprtext, file=sys.stderr, flush=True)
        print(f"{'='*60}\n", file=sys.stderr, flush=True)


def pytest_configure(config):
    """Use SelectorEventLoop on Windows to avoid ProactorEventLoop issues."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ---------------------------------------------------------------------------
# Speed up bcrypt for tests.  Default rounds=12 costs ~0.3 s per hash/verify
# which makes 400+ API tests take minutes.  rounds=4 is the minimum and
# brings the cost down to < 1 ms.
# ---------------------------------------------------------------------------

_real_gensalt = bcrypt.gensalt


@pytest.fixture(autouse=True, scope="session")
def _fast_bcrypt():
    """Globally reduce bcrypt work-factor so auth fixtures run fast."""
    with patch("eiskaltdcpp.api.auth.bcrypt.gensalt",
               side_effect=lambda rounds=4, prefix=b"2b": _real_gensalt(rounds=4, prefix=prefix)):
        yield
