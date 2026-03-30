package com.example.myapplication.llama

import com.example.myapplication.llama.internal.StubInferenceEngine
import com.example.myapplication.llama.internal.NativeInferenceEngine

/**
 * Main entry point for the future llama.cpp-backed library module.
 * The shape mirrors the official llama.android sample so later migration is mechanical.
 */
object AiChat {
    private val engine: InferenceEngine by lazy {
        runCatching { NativeInferenceEngine() }.getOrElse { StubInferenceEngine() }
    }

    fun getInferenceEngine(): InferenceEngine = engine
}
