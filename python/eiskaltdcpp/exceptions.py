"""
Typed exceptions for eiskaltdcpp-py.

These exceptions are raised by the SWIG bridge and the Python wrappers
to provide structured error handling for Lua scripting operations.

Exception hierarchy::

    LuaError (RuntimeError)
    ├── LuaNotAvailableError   — library not compiled with LUA_SCRIPT
    ├── LuaSymbolError         — Lua C API symbols not resolvable at runtime
    ├── LuaLoadError           — Lua code failed to compile (syntax error)
    └── LuaRuntimeError        — Lua code compiled but raised an error
"""


class LuaError(RuntimeError):
    """Base exception for all Lua scripting errors."""


class LuaNotAvailableError(LuaError):
    """Lua is not available (library not compiled with LUA_SCRIPT)."""


class LuaSymbolError(LuaError):
    """Lua C API symbols could not be resolved at runtime."""


class LuaLoadError(LuaError):
    """A Lua chunk failed to compile (syntax error)."""


class LuaRuntimeError(LuaError):
    """A Lua chunk compiled but raised a runtime error."""
