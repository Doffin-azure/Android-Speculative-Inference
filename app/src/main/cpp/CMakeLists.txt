cmake_minimum_required(VERSION 3.22.1)

project("llama_jni")

# Legacy JNI target kept for reference while the real integration moves to :lib.
add_library(
    llama-jni
    SHARED
    llama_jni.cpp
)

find_library(
    log-lib
    log
)

target_link_libraries(
    llama-jni
    ${log-lib}
)
