cmake_minimum_required(VERSION 3.22.1)

project("ai_chat_jni")

set(USE_LLAMA_CPP OFF)

if (DEFINED LLAMA_CPP_SRC AND EXISTS "${LLAMA_CPP_SRC}/CMakeLists.txt")
    message(STATUS "Using external llama.cpp source: ${LLAMA_CPP_SRC}")
    set(USE_LLAMA_CPP ON)
else()
    message(STATUS "Using stub ai_chat.cpp. Provide -DLLAMA_CPP_SRC=/path/to/llama.cpp to switch to real integration.")
endif()

add_library(
        ai-chat-jni
        SHARED
        ai_chat.cpp
)

find_library(
        log-lib
        log
)

if (USE_LLAMA_CPP)
    add_compile_definitions(USE_REAL_LLAMA_CPP=1)
endif()

target_link_libraries(
        ai-chat-jni
        ${log-lib}
)
