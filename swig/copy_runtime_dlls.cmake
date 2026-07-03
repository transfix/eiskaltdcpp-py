#
# copy_runtime_dlls.cmake — Copy vcpkg runtime DLLs to the build output
#
# Called as a POST_BUILD script with:
#   -DSOURCE_DIR=<vcpkg-bin-dir>
#   -DDEST_DIR=<target-dir-containing-.pyd>
#
# Copies only the DLLs that _dc_core.pyd actually needs at runtime.
# This prevents MSYS2's MinGW-ABI DLLs (on PATH) from being loaded
# instead of vcpkg's MSVC-ABI versions.
#

if(NOT SOURCE_DIR OR NOT DEST_DIR)
    message(FATAL_ERROR "SOURCE_DIR and DEST_DIR must be set")
endif()

# DLL base names that _dc_core.pyd needs (via dcpp static lib).
# These are the vcpkg package names → runtime DLL patterns.
set(_DLL_PATTERNS
    "libssl*.dll"
    "libcrypto*.dll"
    "bz2*.dll"
    "zlib*.dll"
    "intl*.dll"
    "libintl*.dll"
    "iconv*.dll"
    "libiconv*.dll"
    "pcre2*.dll"
    "miniupnpc*.dll"
    "idn2*.dll"
    "libidn2*.dll"
    "lua*.dll"
    # gettext runtime dependency
    "charset*.dll"
    "libcharset*.dll"
    # libunistring (idn2 dependency)
    "unistring*.dll"
    "libunistring*.dll"
)

set(_COPIED 0)
foreach(_pattern ${_DLL_PATTERNS})
    file(GLOB _matches "${SOURCE_DIR}/${_pattern}")
    foreach(_dll ${_matches})
        get_filename_component(_name "${_dll}" NAME)
        # Skip debug DLLs (names ending in 'd.dll' from vcpkg debug/)
        file(COPY "${_dll}" DESTINATION "${DEST_DIR}")
        math(EXPR _COPIED "${_COPIED} + 1")
    endforeach()
endforeach()

message(STATUS "Copied ${_COPIED} vcpkg runtime DLLs to ${DEST_DIR}")
