"""
Shared pytest configuration for eiskaltdcpp-py tests.
"""
from __future__ import annotations

from unittest.mock import patch

import bcrypt
import pytest

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
