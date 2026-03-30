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

    suspend fun setSystemPrompt(systemPrompt: String)

    fun sendUserPrompt(message: String, predictLength: Int = DEFAULT_PREDICT_LENGTH): Flow<String>

    suspend fun bench(pp: Int, tg: Int, pl: Int, nr: Int = 1): String

    fun cleanUp()

    fun destroy()

    fun generate(prompt: String, maxTokens: Int = DEFAULT_MAX_TOKENS): Flow<String> {
        return sendUserPrompt(prompt, maxTokens)
    }

    fun unloadModel() {
        cleanUp()
    }

    sealed class State {
        data object Uninitialized : State()
        data object Initializing : State()
        data object Initialized : State()
        data object LoadingModel : State()
        data object UnloadingModel : State()
        data object ModelReady : State()
        data object Benchmarking : State()
        data object ProcessingSystemPrompt : State()
        data object ProcessingUserPrompt : State()
        data object Generating : State()
        data class Error(val message: String) : State()
    }

    companion object {
        const val DEFAULT_PREDICT_LENGTH = 128
        const val DEFAULT_MAX_TOKENS = 128
    }
}

val InferenceEngine.State.isUninterruptible: Boolean
    get() = this is InferenceEngine.State.Initializing ||
        this is InferenceEngine.State.LoadingModel ||
        this is InferenceEngine.State.UnloadingModel ||
        this is InferenceEngine.State.Benchmarking ||
        this is InferenceEngine.State.ProcessingSystemPrompt ||
        this is InferenceEngine.State.ProcessingUserPrompt

val InferenceEngine.State.isModelLoaded: Boolean
    get() = this is InferenceEngine.State.ModelReady ||
        this is InferenceEngine.State.Benchmarking ||
        this is InferenceEngine.State.ProcessingSystemPrompt ||
        this is InferenceEngine.State.ProcessingUserPrompt ||
        this is InferenceEngine.State.Generating
