#
# eiskaltdcpp-py/swig — SWIG Python module build
#
# Follows the pattern from verlihub/src/swig/CMakeLists.txt:
#   - Uses swig_add_library() with the .i file
#   - Links against our static bridge library + Python3::Python
#   - Outputs _dc_core.so and dc_core.py to python/eiskaltdcpp/
#

# Set SWIG flags
set(CMAKE_SWIG_FLAGS -threads -Wall)

# SWIG interface file properties
set_source_files_properties(
    dc_core.i
    PROPERTIES
        CPLUSPLUS ON
        SWIG_MODULE_NAME dc_core
        USE_TARGET_INCLUDE_DIRECTORIES TRUE
)

# Create the SWIG module
swig_add_library(dc_core
    TYPE SHARED
    LANGUAGE python
    OUTPUT_DIR ${CMAKE_BINARY_DIR}/python/eiskaltdcpp
    OUTFILE_DIR ${CMAKE_BINARY_DIR}/swig
    SOURCES dc_core.i
)

# Include directories for the SWIG wrapper compilation
target_include_directories(dc_core
    PRIVATE
        ${CMAKE_SOURCE_DIR}/src
        ${EISKALTDCPP_INCLUDE_DIR}
        ${Python3_INCLUDE_DIRS}
)

# Link against bridge static library and Python
target_link_libraries(dc_core
    PRIVATE
        eiskaltdcpp_py_bridge
        Python3::Python
)

# Set output name: _dc_core.so (SWIG convention: underscore prefix)
set_target_properties(dc_core PROPERTIES
    PREFIX ""
    OUTPUT_NAME "_dc_core"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python/eiskaltdcpp"
)

# Platform-specific suffix
if(WIN32)
    set_target_properties(dc_core PROPERTIES SUFFIX ".pyd")
else()
    set_target_properties(dc_core PROPERTIES SUFFIX ".so")
endif()

# ---------------------------------------------------------------------------
# Copy pure-Python source files to the build tree so tests can find them.
# Uses a stamp-file custom command that re-runs when any .py source changes.
# ---------------------------------------------------------------------------
set(_PY_SRCS
    ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/__init__.py
    ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/dc_client.py
    ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/async_client.py
)
set(_PY_STAMP ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/.py_copy_stamp)

add_custom_command(
    OUTPUT ${_PY_STAMP}
    DEPENDS ${_PY_SRCS}
    COMMAND ${CMAKE_COMMAND} -E make_directory
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/__init__.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/__init__.py
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/dc_client.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/dc_client.py
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/async_client.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/async_client.py
    COMMAND ${CMAKE_COMMAND} -E touch ${_PY_STAMP}
    COMMENT "Syncing Python sources to build tree"
)
add_custom_target(sync_python_sources ALL DEPENDS ${_PY_STAMP})
add_dependencies(dc_core sync_python_sources)

# Copy SWIG-generated .so and dc_core.py (POST_BUILD, since they
# only exist after the SWIG compile/link step)
add_custom_command(TARGET dc_core POST_BUILD
    COMMENT "SWIG Python module built: dc_core"
)

# Ensure _version.py is also in the build tree for tests
add_custom_command(TARGET dc_core POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
    COMMENT "Version file synced"
)

# ---------------------------------------------------------------------------
# Install destinations
#
# When scikit-build-core drives the build it defines SKBUILD and sets
# CMAKE_INSTALL_PREFIX to a staging directory.  pyproject.toml's
# wheel.install-dir = "eiskaltdcpp" means DESTINATION "." inside the
# staging dir already maps to the eiskaltdcpp/ package directory in the
# wheel.
#
# For standalone cmake builds (cmake .. && make && make install) we keep
# the original behaviour of installing into Python3_SITEARCH.
# ---------------------------------------------------------------------------
if(DEFINED SKBUILD)
    set(_PY_INSTALL_DIR ".")
else()
    set(_PY_INSTALL_DIR "${Python3_SITEARCH}/eiskaltdcpp")
endif()

# Install the SWIG module
install(TARGETS dc_core
    LIBRARY DESTINATION ${_PY_INSTALL_DIR}
    COMPONENT PythonModule
)

install(FILES
    ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/dc_core.py
    DESTINATION ${_PY_INSTALL_DIR}
    COMPONENT PythonModule
)

# Install generated _version.py
install(FILES
    ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
    DESTINATION ${_PY_INSTALL_DIR}
    COMPONENT PythonModule
)

# For standalone cmake installs, also install the Python source files.
# When using scikit-build-core, wheel.packages handles this automatically.
if(NOT DEFINED SKBUILD)
    install(DIRECTORY
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/
        DESTINATION ${_PY_INSTALL_DIR}
        COMPONENT PythonModule
        FILES_MATCHING PATTERN "*.py"
    )
endif()
