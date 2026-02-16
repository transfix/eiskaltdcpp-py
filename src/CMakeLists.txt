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
