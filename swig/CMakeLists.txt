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

# Ensure the output directory and __init__.py exist
add_custom_command(TARGET dc_core POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/__init__.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/__init__.py
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/dc_client.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/dc_client.py
    COMMENT "SWIG Python module built: dc_core"
)

# Ensure _version.py is also in the build tree for tests
add_custom_command(TARGET dc_core POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
        ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
    COMMENT "Version file synced"
)

# Install the SWIG module
install(TARGETS dc_core
    LIBRARY DESTINATION ${Python3_SITEARCH}/eiskaltdcpp
    COMPONENT PythonModule
)

install(FILES
    ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/dc_core.py
    DESTINATION ${Python3_SITEARCH}/eiskaltdcpp
    COMPONENT PythonModule
)

# Install Python package files
install(DIRECTORY
    ${CMAKE_SOURCE_DIR}/python/eiskaltdcpp/
    DESTINATION ${Python3_SITEARCH}/eiskaltdcpp
    COMPONENT PythonModule
    FILES_MATCHING PATTERN "*.py"
)

# Install generated _version.py
install(FILES
    ${CMAKE_BINARY_DIR}/python/eiskaltdcpp/_version.py
    DESTINATION ${Python3_SITEARCH}/eiskaltdcpp
    COMPONENT PythonModule
)
