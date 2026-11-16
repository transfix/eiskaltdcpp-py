#!/usr/bin/env bash
# eiskaltdcpp-py smoke test, run by cvcpkg on the staged tree before packing: the module imports
# against the eiskaltdcpp core in the deps prefix, a client starts the core with its own config
# directory, a setting round-trips and the core shuts down. HOME points into a temp dir.
set -euo pipefail
: "${CVC_INSTALL_DIR:?CVC_INSTALL_DIR must be set}"
: "${CVC_DEPS_PREFIX:?CVC_DEPS_PREFIX must be set}"
PYVER=3.12

py="${CVC_DEPS_PREFIX}/bin/python${PYVER}"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
export HOME="$T" PYTHONNOUSERSITE=1
export PYTHONPATH="${CVC_INSTALL_DIR}/lib/python${PYVER}/site-packages"
export LD_LIBRARY_PATH="${CVC_DEPS_PREFIX}/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

"$py" - "$T/cfg/" <<'PY'
import sys
import eiskaltdcpp
from eiskaltdcpp import DCClient

assert eiskaltdcpp.__version__.startswith("2.6.0"), eiskaltdcpp.__version__
c = DCClient(sys.argv[1])
assert c.initialize(), "the core did not initialize"
c.set_setting("Nick", "cvcpkg-smoke")
assert c.get_setting("Nick") == "cvcpkg-smoke", c.get_setting("Nick")
c.shutdown()
print("eiskaltdcpp", eiskaltdcpp.__version__, "from", eiskaltdcpp.__file__)
PY
echo "eiskaltdcpp-py smoke test OK"
