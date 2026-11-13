# Invoked by the build, not by source inspection; refreshes incremental builds too.
if(NOT DEFINED OUTPUT_FILE)
    message(FATAL_ERROR "OUTPUT_FILE is required")
endif()
string(TIMESTAMP build_seconds "%s" UTC)
file(WRITE "${OUTPUT_FILE}" "#pragma once\n#include <stdint.h>\n#define APP_BUILD_UNIX_TIME UINT64_C(${build_seconds})\n")
