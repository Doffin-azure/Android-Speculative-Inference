package com.example.myapplication.llama

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

interface InferenceEngine {
    val state: StateFlow<State>

    fun backendLabel(): String

    fun isModelLoaded(): Boolean

    fun loadedModelPath(): String

    fun lastError(): String

    suspend fun loadModel(pathToModel: String)

    fun generate(prompt: String, maxTokens: Int = DEFAULT_MAX_TOKENS): Flow<String>

    fun unloadModel()

    sealed class State {
        data object Uninitialized : State()
        data object LoadingModel : State()
        data object ModelReady : State()
        data object Generating : State()
        data class Error(val message: String) : State()
    }

    companion object {
        const val DEFAULT_MAX_TOKENS = 128
    }
}
