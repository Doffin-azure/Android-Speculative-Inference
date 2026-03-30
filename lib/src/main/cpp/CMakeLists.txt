cmake_minimum_required(VERSION 3.22.1)

project("ai_chat_jni")

add_library(
    ai-chat-jni
    SHARED
    ai_chat_stub.cpp
)

find_library(
    log-lib
    log
)

target_link_libraries(
    ai-chat-jni
    ${log-lib}
)
