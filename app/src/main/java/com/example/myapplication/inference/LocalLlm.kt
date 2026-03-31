package com.example.myapplication.inference

import com.example.myapplication.llama.DraftSessionHandle

interface LocalLlm {
    fun backendLabel(): String
    fun isModelLoaded(): Boolean
    fun loadedModelPath(): String
    fun lastError(): String
    fun supportsDraftSession(): Boolean = false
    suspend fun loadModel(modelPath: String): Boolean
    suspend fun setSystemPrompt(systemPrompt: String): Boolean
    suspend fun generate(prompt: String, maxTokens: Int = 32): String
    suspend fun startDraftSession(systemPrompt: String, userPrompt: String, predictLength: Int = 128): DraftSessionHandle {
        throw UnsupportedOperationException("Draft session is not implemented by this LocalLlm.")
    }
    suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        throw UnsupportedOperationException("Draft token generation is not implemented by this LocalLlm.")
    }
    suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle {
        throw UnsupportedOperationException("Applying verified tokens is not implemented by this LocalLlm.")
    }
    suspend fun closeDraftSession(sessionId: String) {}
    suspend fun benchmark(pp: Int, tg: Int, pl: Int, nr: Int = 1): String
    fun cleanup()
}
