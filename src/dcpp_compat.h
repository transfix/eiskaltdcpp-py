/*
 * eiskaltdcpp-py — Python SWIG bindings for libeiskaltdcpp
 *
 * dcpp_compat.h — Compatibility header for dcpp system headers.
 *
 * The dcpp core was designed to be compiled with stdinc.h as a precompiled
 * header that includes all STL headers and provides `using namespace std`
 * inside namespace dcpp.  The system package (libeiskaltdcpp-dev on Ubuntu)
 * does NOT install stdinc.h, so the installed headers reference bare
 * `string`, `map`, etc. without the `std::` prefix.
 *
 * This header replicates the essential parts of stdinc.h.
 * It MUST be included before any <dcpp/...> headers.
 */

#pragma once

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>

#include <algorithm>
#include <deque>
#include <functional>
#include <limits>
#include <list>
#include <map>
#include <memory>
#include <numeric>
#include <set>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace dcpp {
using namespace std;
}
