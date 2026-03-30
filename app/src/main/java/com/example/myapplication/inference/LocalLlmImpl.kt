package com.example.myapplication.inference

import android.content.Context
import com.example.myapplication.llama.AiChat
import com.example.myapplication.llama.InferenceEngine
import kotlinx.coroutines.flow.firstOrNull

class LocalLlmImpl(context: Context) : LocalLlm {
    private val engine: InferenceEngine = AiChat.getInferenceEngine(context.applicationContext)

    override fun backendLabel(): String {
        return engine.backendLabel()
    }

    override fun isModelLoaded(): Boolean {
        return engine.isModelLoaded()
    }

    override fun loadedModelPath(): String {
        return engine.loadedModelPath()
    }

    override fun lastError(): String {
        return engine.lastError()
    }

    override suspend fun loadModel(modelPath: String): Boolean {
        engine.loadModel(modelPath)
        return when (val state = engine.state.value) {
            is InferenceEngine.State.ModelReady -> true
            is InferenceEngine.State.Error -> false
            else -> false
        }
    }

    override suspend fun generate(prompt: String, maxTokens: Int): String {
        val output = engine.generate(prompt, maxTokens).firstOrNull()
        return when (val state = engine.state.value) {
            is InferenceEngine.State.Error -> state.message
            else -> output ?: ""
        }
    }

    override suspend fun draftTokenIds(prompt: String, count: Int): List<Int> {
        return (1..count).toList()
    }
}
