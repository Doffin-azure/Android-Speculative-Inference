package com.example.myapplication.inference

interface LocalLlm {
    fun backendLabel(): String
    fun isModelLoaded(): Boolean
    fun loadedModelPath(): String
    fun lastError(): String
    suspend fun loadModel(modelPath: String): Boolean
    suspend fun generate(prompt: String, maxTokens: Int = 32): String
    suspend fun draftTokenIds(prompt: String, count: Int = 4): List<Int>
}
