#!/usr/bin/env bash
# eiskaltdcpp-py-cp312: the SWIG bindings, built from source as a wheel (scikit-build-core, no
# build isolation) against the eiskaltdcpp core in the deps prefix, and pip-installed into this
# column's site-packages.
set -euo pipefail

: "${CVC_SOURCE_DIR:?CVC_SOURCE_DIR must be set}"
: "${CVC_BUILD_DIR:?CVC_BUILD_DIR must be set}"
: "${CVC_INSTALL_DIR:?CVC_INSTALL_DIR must be set}"
: "${CVC_DEPS_PREFIX:?CVC_DEPS_PREFIX must be set}"

PYVER=3.12
PKG=eiskaltdcpp_py
deps="${CVC_DEPS_PREFIX}"

PY_EXE=""
for d in "${deps}" "${CVC_BUILD_PREFIX:-}"; do
  if [[ -n "$d" && -x "$d/bin/python${PYVER}" ]]; then PY_EXE="$d/bin/python${PYVER}"; break; fi
done
[[ -n "${PY_EXE}" ]] || { echo "eiskaltdcpp-py: no python${PYVER} in the deps or build prefix" >&2; exit 1; }
echo "eiskaltdcpp-py: building with ${PY_EXE}"

# Only the declared closure is importable: the backend (scikit-build-core and its deps) lives in
# the build prefix, the interpreter in the deps prefix.
export PYTHONNOUSERSITE=1
if [[ -n "${CVC_BUILD_PREFIX:-}" ]]; then
  export PYTHONPATH="${CVC_BUILD_PREFIX}/lib/python${PYVER}/site-packages${PYTHONPATH:+:${PYTHONPATH}}"
  export PATH="${CVC_BUILD_PREFIX}/bin:${PATH}"
fi

# The core's ABI flags (see recipe.yaml notes), and the include roots its headers need: the
# generated proto/ beside dcpp/, and protobuf/abseil in the prefix.
flags_file="${deps}/share/eiskaltdcpp/build-flags.txt"
[[ -f "${flags_file}" ]] || { echo "eiskaltdcpp-py: ${flags_file} missing; is eiskaltdcpp installed?" >&2; exit 1; }
defs=""
while read -r f; do
  case "$f" in ''|'#'*) ;; *) defs="${defs} -D${f}" ;; esac
done < "${flags_file}"
export CXXFLAGS="${CXXFLAGS:-} -O2 -fPIC${defs} -I${deps}/include/eiskaltdcpp -I${deps}/include"
echo "eiskaltdcpp-py: CXXFLAGS=${CXXFLAGS}"

prefix_path="${deps}"
if [[ -n "${CVC_BUILD_PREFIX:-}" && "${CVC_BUILD_PREFIX}" != "${deps}" ]]; then
  prefix_path="${deps};${CVC_BUILD_PREFIX}"
fi
# scikit-build-core passes CMAKE_ARGS to the configure. EISKALTDCPP_SDK_DIR makes the bindings
# take this prefix's core (searched NO_DEFAULT_PATH) and never fetch or build their own.
export CMAKE_ARGS="-DEISKALTDCPP_SDK_DIR=${deps} -DUSE_SYSTEM_EISKALTDCPP=OFF -DBUILD_TESTS=OFF -DCMAKE_PREFIX_PATH=${prefix_path} -DPython3_EXECUTABLE=${PY_EXE}"
export CMAKE_GENERATOR=Ninja
export CMAKE_BUILD_PARALLEL_LEVEL="${CVC_JOBS:-$(nproc 2>/dev/null || echo 4)}"

wheelhouse="${CVC_BUILD_DIR}/wheelhouse"
mkdir -p "${wheelhouse}"
"${PY_EXE}" -m pip wheel --no-deps --no-build-isolation --no-index --no-cache-dir \
  --config-settings=build-dir="${CVC_BUILD_DIR}/skbuild" \
  --wheel-dir "${wheelhouse}" "${CVC_SOURCE_DIR}"
wheel="$(find "${wheelhouse}" -maxdepth 1 -name "${PKG}-*.whl" | sed -n 1p)"
[[ -n "${wheel}" ]] || { echo "eiskaltdcpp-py: no wheel under ${wheelhouse}" >&2; exit 1; }
echo "eiskaltdcpp-py: built $(basename "${wheel}")"

"${PY_EXE}" -m pip install --no-index --no-deps --no-compile --ignore-installed \
  --prefix "${CVC_INSTALL_DIR}" "${wheel}"

site="${CVC_INSTALL_DIR}/lib/python${PYVER}/site-packages"
mod="${site}/eiskaltdcpp"
[[ -d "${mod}" ]] || { echo "eiskaltdcpp-py: ${mod} not staged" >&2; exit 1; }

# The [api] server's dependencies are not packaged (recipe.yaml notes): drop its entry point.
rm -f "${CVC_INSTALL_DIR}/bin/eiskaltdcpp-api"

# The extension links libeiskaltdcpp from <prefix>/lib: make that $ORIGIN-relative.
while IFS= read -r -d '' so; do
  rel="$("${PY_EXE}" -c 'import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' \
    "${CVC_INSTALL_DIR}/lib" "$(dirname "${so}")")"
  patchelf --set-rpath "\$ORIGIN:\$ORIGIN/${rel}" "${so}"
done < <(find "${mod}" -name '*.so' -print0)

echo "cvcpkg: eiskaltdcpp-py-cp312 -> ${site}"
