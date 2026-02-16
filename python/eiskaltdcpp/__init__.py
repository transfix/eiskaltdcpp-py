# eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
#
# This package provides:
# - SWIG-generated dc_core module (low-level C++ bridge)
# - DCClient high-level Python wrapper with callback routing
#
# Copyright (C) 2026 Verlihub Team
# Licensed under GPL-3.0-or-later

__version__ = "0.1.0"

# Import high-level wrapper when SWIG module is available
try:
    from eiskaltdcpp.dc_client import DCClient
    __all__ = ["DCClient", "__version__"]
except ImportError:
    # SWIG module not yet built — only version available
    __all__ = ["__version__"]
