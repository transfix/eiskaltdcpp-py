#
# eiskaltdcpp-py/src — Static bridge library
#
# Builds the C++ bridge layer that sits between SWIG/Python and libeiskaltdcpp.
# This is a static library with PIC so it can be linked into the SWIG .so module.
#

set(BRIDGE_SOURCES
    bridge.cpp
    bridge_listeners.cpp
)

set(BRIDGE_HEADERS
    bridge.h
    bridge_listeners.h
    callbacks.h
    dcpp_compat.h
    types.h
)

add_library(eiskaltdcpp_py_bridge STATIC
    ${BRIDGE_SOURCES}
    ${BRIDGE_HEADERS}
)

# Position-independent code required for linking into shared SWIG module
set_target_properties(eiskaltdcpp_py_bridge PROPERTIES
    POSITION_INDEPENDENT_CODE ON
)

target_include_directories(eiskaltdcpp_py_bridge
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
    PRIVATE
        ${EISKALTDCPP_INCLUDE_DIR}
)

target_link_libraries(eiskaltdcpp_py_bridge
    PUBLIC
        eiskaltdcpp::dcpp
)

# System libs that dcpp depends on transitively
find_package(OpenSSL REQUIRED)
find_package(ZLIB REQUIRED)
find_package(BZip2 REQUIRED)
find_package(Threads REQUIRED)

target_link_libraries(eiskaltdcpp_py_bridge
    PRIVATE
        OpenSSL::SSL
        OpenSSL::Crypto
        ZLIB::ZLIB
        BZip2::BZip2
        Threads::Threads
)

# When the system libeiskaltdcpp is compiled with LUA_SCRIPT, the Client
# class has an extra base class (ClientScriptInstance -> ScriptInstance)
# which adds a vtable pointer and changes member offsets.  We must compile
# with the same define to match the ABI.
if(EISKALTDCPP_HAS_LUA)
    target_compile_definitions(eiskaltdcpp_py_bridge PRIVATE LUA_SCRIPT)
    # Lua headers needed by dcpp/ScriptManager.h (which is pulled in
    # transitively via dcpp/NmdcHub.h when LUA_SCRIPT is defined).
    # We use them ONLY for type definitions (lua_State*, Lunar<T>);
    # all actual Lua C API calls are resolved at runtime via dlsym
    # from the same liblua that libeiskaltdcpp.so loaded, ensuring
    # ABI compatibility even if the dev headers are a different Lua
    # version than the runtime library.
    target_include_directories(eiskaltdcpp_py_bridge PRIVATE ${LUA_INCLUDE_DIR})
    # Our src/extra/lunar.h stub (ScriptManager.h includes "extra/lunar.h"
    # which is not installed by libeiskaltdcpp-dev)
    target_include_directories(eiskaltdcpp_py_bridge PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
    )
endif()
