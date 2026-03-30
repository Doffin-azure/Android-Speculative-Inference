cmake_minimum_required(VERSION 3.22.1)

project("ai-chat" VERSION 1.0.0 LANGUAGES C CXX)

set(USE_LLAMA_CPP OFF)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED true)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED true)
set(CMAKE_C_FLAGS   "${CMAKE_C_FLAGS}"   CACHE STRING "" FORCE)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}" CACHE STRING "" FORCE)

if(DEFINED ANDROID_ABI)
    message(STATUS "Detected Android ABI: ${ANDROID_ABI}")
    if(ANDROID_ABI STREQUAL "arm64-v8a")
        set(GGML_SYSTEM_ARCH "ARM")
        set(GGML_CPU_KLEIDIAI ON)
        set(GGML_OPENMP ON)
    elseif(ANDROID_ABI STREQUAL "x86_64")
        set(GGML_SYSTEM_ARCH "x86")
        set(GGML_CPU_KLEIDIAI OFF)
        set(GGML_OPENMP OFF)
    else()
        message(FATAL_ERROR "Unsupported ABI: ${ANDROID_ABI}")
    endif()
endif()

# Actual llama.cpp source integration starts by providing LLAMA_CPP_SRC,
# then replacing the current stub implementation in ai_chat.cpp with the
# official llama.android/lib native wiring.
if (DEFINED LLAMA_CPP_SRC AND EXISTS "${LLAMA_CPP_SRC}/CMakeLists.txt")
    message(STATUS "Using external llama.cpp source: ${LLAMA_CPP_SRC}")
    set(USE_LLAMA_CPP ON)
    set(LLAMA_SRC "${LLAMA_CPP_SRC}")
else()
    message(STATUS "Using stub ai_chat.cpp. Provide -DLLAMA_CPP_SRC=/path/to/llama.cpp to switch to real integration.")
endif()

add_library(
        ${CMAKE_PROJECT_NAME}
        SHARED
        ai_chat.cpp
)

find_library(
        log-lib
        log
)

if (USE_LLAMA_CPP)
    add_compile_definitions(USE_REAL_LLAMA_CPP=1)
    add_subdirectory(${LLAMA_SRC} build-llama)

    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
            GGML_SYSTEM_ARCH=${GGML_SYSTEM_ARCH}
            GGML_CPU_KLEIDIAI=$<BOOL:${GGML_CPU_KLEIDIAI}>
            GGML_OPENMP=$<BOOL:${GGML_OPENMP}>
    )

    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
            ${LLAMA_SRC}
            ${LLAMA_SRC}/common
            ${LLAMA_SRC}/include
            ${LLAMA_SRC}/ggml/include
            ${LLAMA_SRC}/ggml/src)
endif()

target_link_libraries(
        ${CMAKE_PROJECT_NAME}
        ${log-lib}
)

if (USE_LLAMA_CPP)
    target_link_libraries(
            ${CMAKE_PROJECT_NAME}
            llama
            common
            android)
endif()
