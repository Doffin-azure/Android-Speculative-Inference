package com.example.myapplication.llama

import android.content.Context
import com.example.myapplication.llama.internal.InferenceEngineImpl
import com.example.myapplication.llama.internal.StubInferenceEngine

/**
 * Main entry point for the future llama.cpp-backed library module.
 * The shape mirrors the official llama.android sample so later migration is mechanical.
 */
object AiChat {
    private val fallbackEngine: InferenceEngine by lazy { StubInferenceEngine() }

    fun getInferenceEngine(context: Context): InferenceEngine {
        return runCatching { InferenceEngineImpl.getInstance(context) }
            .getOrElse { fallbackEngine }
    }

    @Deprecated("Prefer the context-aware overload to match llama.android integration.")
    fun getInferenceEngine(): InferenceEngine = fallbackEngine
}
