#!/usr/bin/env bash
# eiskaltdcpp-py smoke test, run by cvcpkg on the staged tree before packing: the module imports
# against the eiskaltdcpp core in the deps prefix, a client starts the core with its own config
# directory, a setting round-trips, a download can be queued by TTH and the core shuts down. Then
# eiskaltdcpp-interop starts, says ready, rejects a command that needs a hub and exits 0 on quit.
# HOME points into a temp dir.
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
# The managers take TTHValue: a download queued by TTH alone shows up in the queue.
from eiskaltdcpp import dc_core
tth = "LWPNACQDBZRYXW3VHJVCJ64QBZNGHOHHHZWCLNQ"
target = sys.argv[1] + "queued.bin"
c.queue.add(target, 1234, dc_core.TTHValue(tth))
assert any(q.tth == tth and q.size == 1234 for q in c.list_queue()), "queue.add did not queue"
c.queue.remove(target)
c.shutdown()
print("eiskaltdcpp", eiskaltdcpp.__version__, "from", eiskaltdcpp.__file__)
PY
# eiskaltdcpp-interop: from the installed launcher when the interpreter is in the same prefix
# (after `cvcpkg install`), else as a module from the staged tree.
if [[ -x "${CVC_INSTALL_DIR}/bin/python${PYVER}" ]]; then
  drv=("${CVC_INSTALL_DIR}/bin/eiskaltdcpp-interop")
else
  drv=("$py" -s -m eiskaltdcpp.interop)
fi
mkdir -p "$T/share" "$T/dl"
head -c 65536 /dev/urandom > "$T/share/smoke.bin"
"$py" - "$T" "${drv[@]}" <<'PY'
import json, subprocess, sys, time
T, cmd = sys.argv[1], sys.argv[2:]
p = subprocess.Popen(cmd + ["--nick", "smoke", "--share", T + "/share", "--download-dir", T + "/dl",
                            "--passive", "--log", T + "/interop.log"],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
ev = json.loads(p.stdout.readline())
assert ev["event"] == "ready" and ev["version"].startswith("2.6"), ev
p.stdin.write('{"op":"users"}\n')
p.stdin.flush()
ev = json.loads(p.stdout.readline())
assert ev["event"] == "error" and ev["op"] == "users", ev
t0 = time.monotonic()
p.stdin.write('{"op":"quit"}\n')
p.stdin.flush()
assert p.wait(timeout=12) == 0 and time.monotonic() - t0 < 10, p.returncode
rest = p.stdout.read()
assert not rest.strip(), rest
print("eiskaltdcpp-interop: ready, error before connect, exit 0 on quit")
PY
echo "eiskaltdcpp-py smoke test OK"
