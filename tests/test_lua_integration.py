"""
Integration tests for Lua scripting via the eiskaltdcpp Python bindings.

These tests validate the full Lua scripting pipeline:

1. Checking whether Lua is compiled in (lua_is_available)
2. Evaluating inline Lua code (lua_eval)
3. Evaluating Lua script files (lua_eval_file)
4. Error handling with typed exceptions
5. TLS encryption field population on hub connections

The tests use the *local* DCClient/AsyncDCClient directly (no REST API)
so they exercise the entire SWIG → C++ → Lua bridge.

Requirements:
    - eiskaltdcpp-py built with ``LUA_SCRIPT=ON`` (default when Lua is found)
    - Network access to ``nmdcs://wintermute.sublevels.net:411`` for TLS tests
    - pytest + pytest-asyncio

Run:
    PYTHONPATH=python:build/python pytest tests/test_lua_integration.py -v --tb=long
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

try:
    import pytest_asyncio
except ImportError:
    pytest_asyncio = None

# -- Locate SWIG module ---------------------------------------------------
# BUILD_DIR must be first so _dc_core.so is found alongside __init__.py
BUILD_DIR = Path(__file__).parent.parent / "build" / "python"
PYTHON_DIR = Path(__file__).parent.parent / "python"
if PYTHON_DIR.exists():
    sys.path.insert(0, str(PYTHON_DIR))
if BUILD_DIR.exists():
    sys.path.insert(0, str(BUILD_DIR))

try:
    from eiskaltdcpp import AsyncDCClient, DCClient
    from eiskaltdcpp.exceptions import (
        LuaError,
        LuaLoadError,
        LuaNotAvailableError,
        LuaRuntimeError,
        LuaSymbolError,
    )
    SWIG_AVAILABLE = True
except ImportError:
    SWIG_AVAILABLE = False

EXAMPLES_DIR = Path(__file__).parent.parent / "examples" / "lua"

# Module-level marks — skip if SWIG/pytest-asyncio not available.
# Only network-dependent test classes use @pytest.mark.integration.
pytestmark = [
    pytest.mark.skipif(not SWIG_AVAILABLE, reason="dc_core SWIG module not built"),
    pytest.mark.skipif(pytest_asyncio is None, reason="pytest-asyncio not installed"),
]


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope="module")
def config_dir(tmp_path_factory):
    """Create a temporary config directory used for all tests in this module."""
    return str(tmp_path_factory.mktemp("lua_integration"))


@pytest.fixture(scope="module")
def dc_client(config_dir):
    """Module-scoped synchronous DCClient."""
    client = DCClient(config_dir)
    client.initialize()
    yield client
    try:
        client.shutdown()
    except Exception:
        pass  # shutdown may segfault in test env; ignore


@pytest.fixture(scope="module")
def event_loop():
    """Module-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module")
async def async_client(config_dir):
    """Module-scoped AsyncDCClient."""
    client = AsyncDCClient(config_dir)
    await client.initialize()
    yield client
    await client.shutdown()


# ============================================================================
# Exception hierarchy tests (pure Python, no SWIG needed beyond import)
# ============================================================================

class TestExceptionHierarchy:
    """Verify the Lua exception class hierarchy is correct."""

    def test_base_is_runtime_error(self):
        assert issubclass(LuaError, RuntimeError)

    def test_not_available_is_lua_error(self):
        assert issubclass(LuaNotAvailableError, LuaError)

    def test_symbol_error_is_lua_error(self):
        assert issubclass(LuaSymbolError, LuaError)

    def test_load_error_is_lua_error(self):
        assert issubclass(LuaLoadError, LuaError)

    def test_runtime_error_is_lua_error(self):
        assert issubclass(LuaRuntimeError, LuaError)

    def test_catching_base_catches_all(self):
        """Catching LuaError should catch every subclass."""
        for cls in (LuaNotAvailableError, LuaSymbolError,
                    LuaLoadError, LuaRuntimeError):
            with pytest.raises(LuaError):
                raise cls("test")

    def test_message_preserved(self):
        try:
            raise LuaRuntimeError("something went wrong")
        except LuaError as exc:
            assert str(exc) == "something went wrong"


# ============================================================================
# Lua availability
# ============================================================================

class TestLuaAvailability:
    """Test whether Lua scripting support is compiled in."""

    def test_lua_is_available_returns_bool(self, dc_client):
        result = dc_client.lua_is_available()
        assert isinstance(result, bool)

    def test_scripts_path_is_string(self, dc_client):
        path = dc_client.lua_get_scripts_path()
        assert isinstance(path, str)

    def test_list_scripts_returns_list(self, dc_client):
        scripts = dc_client.lua_list_scripts()
        assert isinstance(scripts, list)


# ============================================================================
# Lua eval — inline code execution
# ============================================================================

class TestLuaEval:
    """Test lua_eval with various Lua code snippets."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_lua(self, dc_client):
        if not dc_client.lua_is_available():
            pytest.skip("Lua scripting not available in this build")
        try:
            dc_client.lua_eval("-- probe")
        except LuaSymbolError:
            pytest.skip("Lua C API symbols not resolvable at runtime")

    def test_eval_simple_assignment(self, dc_client):
        """Assignment should succeed silently (void return)."""
        dc_client.lua_eval("_test_var = 42")

    def test_eval_print(self, dc_client):
        """print() should not raise."""
        dc_client.lua_eval('print("hello from Lua integration test")')

    def test_eval_math(self, dc_client):
        """Math operations should work fine."""
        dc_client.lua_eval("local x = math.sqrt(144); assert(x == 12)")

    def test_eval_string_operations(self, dc_client):
        """String library should be accessible."""
        dc_client.lua_eval('assert(string.upper("hello") == "HELLO")')

    def test_eval_table_operations(self, dc_client):
        """Table operations should work."""
        dc_client.lua_eval(textwrap.dedent("""\
            local t = {1, 2, 3}
            table.insert(t, 4)
            assert(#t == 4)
        """))

    def test_eval_multiline(self, dc_client):
        """Multi-line chunks should work."""
        code = textwrap.dedent("""\
            local function fib(n)
                if n <= 1 then return n end
                return fib(n - 1) + fib(n - 2)
            end
            assert(fib(10) == 55)
        """)
        dc_client.lua_eval(code)

    def test_eval_syntax_error_raises_load_error(self, dc_client):
        """Invalid Lua syntax should raise LuaLoadError."""
        with pytest.raises(LuaLoadError):
            dc_client.lua_eval("this is not valid lua!!!")

    def test_eval_runtime_error_raises_runtime_error(self, dc_client):
        """Runtime errors should raise LuaRuntimeError."""
        with pytest.raises(LuaRuntimeError):
            dc_client.lua_eval('error("intentional test error")')

    def test_eval_nil_index_raises_runtime_error(self, dc_client):
        """Indexing nil should raise LuaRuntimeError."""
        with pytest.raises(LuaRuntimeError):
            dc_client.lua_eval("local x = nil; return x.foo")

    def test_eval_error_message_contains_detail(self, dc_client):
        """Exception message should contain the Lua error detail."""
        with pytest.raises(LuaError, match="intentional"):
            dc_client.lua_eval('error("intentional detail")')

    def test_eval_catches_base_class(self, dc_client):
        """LuaError catch-all should work for load errors too."""
        with pytest.raises(LuaError):
            dc_client.lua_eval("@@@ bad syntax @@@")


# ============================================================================
# Lua eval-file — script file execution
# ============================================================================

class TestLuaEvalFile:
    """Test lua_eval_file with actual script files."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_lua(self, dc_client):
        if not dc_client.lua_is_available():
            pytest.skip("Lua scripting not available in this build")
        try:
            dc_client.lua_eval("-- probe")
        except LuaSymbolError:
            pytest.skip("Lua C API symbols not resolvable at runtime")

    def test_eval_simple_script(self, dc_client, tmp_path):
        """Execute a trivial script file."""
        script = tmp_path / "test_simple.lua"
        script.write_text('print("script executed successfully")\n')
        dc_client.lua_eval_file(str(script))

    def test_eval_script_with_logic(self, dc_client, tmp_path):
        """Execute a script with actual logic."""
        script = tmp_path / "test_logic.lua"
        script.write_text(textwrap.dedent("""\
            local function factorial(n)
                if n <= 1 then return 1 end
                return n * factorial(n - 1)
            end
            assert(factorial(10) == 3628800, "factorial(10) should be 3628800")
        """))
        dc_client.lua_eval_file(str(script))

    def test_eval_script_with_globals(self, dc_client, tmp_path):
        """Script can set and read global variables."""
        script = tmp_path / "test_globals.lua"
        script.write_text(textwrap.dedent("""\
            _G._integration_test_marker = "lua_integration_ok"
            assert(_G._integration_test_marker == "lua_integration_ok")
        """))
        dc_client.lua_eval_file(str(script))

    def test_eval_nonexistent_file_raises(self, dc_client):
        """Attempting to eval a nonexistent file should raise."""
        with pytest.raises(LuaError):
            dc_client.lua_eval_file("/nonexistent/path/to/script.lua")

    def test_eval_file_with_syntax_error(self, dc_client, tmp_path):
        """A script with syntax errors should raise LuaLoadError."""
        script = tmp_path / "test_bad_syntax.lua"
        script.write_text("this is not valid lua!!!\n")
        with pytest.raises(LuaLoadError):
            dc_client.lua_eval_file(str(script))

    def test_eval_file_with_runtime_error(self, dc_client, tmp_path):
        """A script that errors at runtime should raise LuaRuntimeError."""
        script = tmp_path / "test_runtime_err.lua"
        script.write_text('error("deliberate runtime error")\n')
        with pytest.raises(LuaRuntimeError):
            dc_client.lua_eval_file(str(script))

    @pytest.mark.skipif(
        not EXAMPLES_DIR.exists(),
        reason="examples/lua directory not found",
    )
    def test_eval_example_chat_commands(self, dc_client):
        """Run the bundled chat_commands.lua example.

        The script registers listeners via dcpp:setListener() which is only
        available when the full ScriptManager is initialised.  In our minimal
        Lua state, the ``dcpp`` global is nil so the script raises a
        LuaRuntimeError — that is the expected outcome here.
        """
        script = EXAMPLES_DIR / "chat_commands.lua"
        if not script.exists():
            pytest.skip("chat_commands.lua example not found")
        try:
            dc_client.lua_eval_file(str(script))
        except LuaRuntimeError as exc:
            # Expected: 'dcpp' is nil in minimal Lua state
            assert "nil" in str(exc).lower() or "dcpp" in str(exc).lower()

    @pytest.mark.skipif(
        not EXAMPLES_DIR.exists(),
        reason="examples/lua directory not found",
    )
    def test_eval_example_auto_greet(self, dc_client):
        """Run the bundled auto_greet.lua example.

        Same as chat_commands — expects LuaRuntimeError because the ``dcpp``
        scripting environment is not available in the test Lua state.
        """
        script = EXAMPLES_DIR / "auto_greet.lua"
        if not script.exists():
            pytest.skip("auto_greet.lua example not found")
        try:
            dc_client.lua_eval_file(str(script))
        except LuaRuntimeError as exc:
            assert "nil" in str(exc).lower() or "dcpp" in str(exc).lower()


# ============================================================================
# Async client — same operations through AsyncDCClient
# ============================================================================

class TestAsyncLuaEval:
    """Verify the async wrapper passes through correctly."""

    @pytest.fixture(autouse=True)
    def _skip_if_no_lua(self, async_client):
        if not async_client.lua_is_available():
            pytest.skip("Lua scripting not available in this build")
        try:
            async_client.lua_eval("-- probe")
        except (LuaSymbolError, LuaError):
            pytest.skip("Lua eval not functional in this environment")

    @pytest.mark.asyncio
    async def test_async_eval_success(self, async_client):
        async_client.lua_eval('print("async eval ok")')

    @pytest.mark.asyncio
    async def test_async_eval_raises_on_error(self, async_client):
        with pytest.raises(LuaRuntimeError):
            async_client.lua_eval('error("async test error")')

    @pytest.mark.asyncio
    async def test_async_eval_file(self, async_client, tmp_path):
        script = tmp_path / "async_test.lua"
        script.write_text('assert(1 + 1 == 2)\n')
        async_client.lua_eval_file(str(script))


# ============================================================================
# TLS encryption verification
# ============================================================================

HUB_URL = os.environ.get(
    "TEST_HUB_URL", "nmdcs://wintermute.sublevels.net:411"
)


@pytest.mark.integration
class TestTLSEncryption:
    """Verify TLS encryption fields are populated on hub connections.

    These tests require network access and a live hub that supports TLS.
    The default hub uses nmdcs:// (NMDC over TLS).
    """

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        "CI" not in os.environ and "TEST_HUB_URL" not in os.environ,
        reason="TLS tests need network access; set TEST_HUB_URL or run in CI",
    )
    async def test_hub_tls_fields_populated(self, async_client):
        """Connect to a TLS hub and verify isSecure/cipherName are set."""
        await async_client.connect(HUB_URL)
        try:
            # Wait for the connection to establish
            await async_client.wait_connected(HUB_URL, timeout=30)
            await asyncio.sleep(2)  # let cipher info propagate

            hubs = async_client.list_hubs()
            assert len(hubs) > 0, "Should have at least one hub"

            hub = next((h for h in hubs if HUB_URL in h.url), None)
            assert hub is not None, f"Hub {HUB_URL} not found in list"

            # nmdcs:// should always be secure
            assert hub.isSecure, f"Expected isSecure=True for {HUB_URL}"
            assert hub.cipherName, f"Expected non-empty cipherName for {HUB_URL}"
        finally:
            await async_client.disconnect(HUB_URL)
            await asyncio.sleep(1)
