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
    # On Windows, .pyd (DLL) goes to RUNTIME_OUTPUT_DIRECTORY
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python/eiskaltdcpp"
    # Suppress per-config subdirs (Release/, Debug/) for multi-config generators
    LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/python/eiskaltdcpp"
    LIBRARY_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}/python/eiskaltdcpp"
    RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}/python/eiskaltdcpp"
    RUNTIME_OUTPUT_DIRECTORY_DEBUG "${CMAKE_BINARY_DIR}/python/eiskaltdcpp"
)

# Platform-specific suffix
if(WIN32)
    set(_DC_CORE_SUFFIX ".pyd")
elseif(APPLE)
    set(_DC_CORE_SUFFIX ".so")  # Python extensions use .so even on macOS
else()
    set(_DC_CORE_SUFFIX ".so")
endif()
set_target_properties(dc_core PROPERTIES SUFFIX "${_DC_CORE_SUFFIX}")

# Ensure the output directory and Python source files exist in build tree
add_custom_command(TARGET dc_core POST_BUILD
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
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/cli.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/cli.py
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/exceptions.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/exceptions.py
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/protocol.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/protocol.py
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/hub_aliases.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/hub_aliases.py
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/api
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/api
    COMMENT "SWIG Python module built: dc_core"
)

# ---------------------------------------------------------------------------
# Dev symlinks — so that "poetry install" (editable) and PYTHONPATH=python/
# can find the SWIG artifacts without having to set PYTHONPATH=build/python/.
# These are gitignored (*.so globally, dc_core.py explicitly).
# On Windows, use copy instead of symlinks (symlinks need admin privileges).
# ---------------------------------------------------------------------------
if(WIN32)
    add_custom_command(TARGET dc_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_dc_core${_DC_CORE_SUFFIX}
            ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/_dc_core${_DC_CORE_SUFFIX}
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/dc_core.py
            ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/dc_core.py
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
            ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/_version.py
        COMMENT "Dev copies created in python/eiskaltdcpp/ for editable installs"
    )
else()
    add_custom_command(TARGET dc_core POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E create_symlink
            ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_dc_core${_DC_CORE_SUFFIX}
            ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/_dc_core${_DC_CORE_SUFFIX}
        COMMAND ${CMAKE_COMMAND} -E create_symlink
            ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/dc_core.py
            ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/dc_core.py
        COMMAND ${CMAKE_COMMAND} -E create_symlink
            ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
            ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/_version.py
        COMMENT "Dev symlinks created in python/eiskaltdcpp/ for editable installs"
    )
endif()

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
