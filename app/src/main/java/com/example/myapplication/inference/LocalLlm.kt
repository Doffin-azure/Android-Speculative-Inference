package com.example.myapplication.inference

interface LocalLlm {
    fun backendLabel(): String
    fun isModelLoaded(): Boolean
    fun loadedModelPath(): String
    fun lastError(): String
    suspend fun loadModel(modelPath: String): Boolean
    suspend fun setSystemPrompt(systemPrompt: String): Boolean
    suspend fun generate(prompt: String, maxTokens: Int = 32): String
    suspend fun benchmark(pp: Int, tg: Int, pl: Int, nr: Int = 1): String
    fun cleanup()
}
