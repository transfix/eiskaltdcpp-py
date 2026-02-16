#
# eiskaltdcpp-py/tests — Test configuration
#
# Uses pytest to run SWIG binding tests.
# Follows the verlihub pattern.
#

# Find pytest
execute_process(
    COMMAND ${Python3_EXECUTABLE} -c "import pytest"
    RESULT_VARIABLE PYTEST_FOUND
    OUTPUT_QUIET ERROR_QUIET
)

if(PYTEST_FOUND EQUAL 0)
    add_test(NAME DcCoreSwigTests
        COMMAND ${Python3_EXECUTABLE} -m pytest
            ${CMAKE_SOURCE_DIR}/tests/test_dc_core.py
            -v --tb=short
        WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
    )
    set_tests_properties(DcCoreSwigTests PROPERTIES
        LABELS "swig;python;unit"
        ENVIRONMENT "PYTHONPATH=${CMAKE_BINARY_DIR}/python:$ENV{PYTHONPATH}"
    )
else()
    message(STATUS "pytest not found, skipping Python tests")
endif()
