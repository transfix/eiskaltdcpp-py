#
# eiskaltdcpp-py/src — Static bridge library
#
# Builds the C++ bridge layer that sits between SWIG/Python and libeiskaltdcpp.
# This is a static library with PIC so it can be linked into the SWIG .so module.
#

set(BRIDGE_SOURCES
    eispy_context.cpp
    bridge_listeners.cpp
)

set(BRIDGE_HEADERS
    eispy_context.h
    bridge_listeners.h
    listener_adapters.h
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
# which adds a vtable pointer and changes member offsets.  Every TU that
# includes dcpp/Client.h MUST see the same class layout, so we use PUBLIC
# to propagate the define and include paths to the SWIG dc_core module
# (which links against this bridge library).
if(EISKALTDCPP_HAS_LUA)
    target_compile_definitions(eiskaltdcpp_py_bridge PUBLIC LUA_SCRIPT)
    # Lua headers needed by dcpp/ScriptManager.h (which is pulled in
    # transitively via dcpp/NmdcHub.h when LUA_SCRIPT is defined).
    target_include_directories(eiskaltdcpp_py_bridge PUBLIC ${LUA_INCLUDE_DIR})
    # Our src/extra/lunar.h stub (ScriptManager.h includes "extra/lunar.h"
    # which is not installed by libeiskaltdcpp-dev)
    target_include_directories(eiskaltdcpp_py_bridge PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
    )
endif()
