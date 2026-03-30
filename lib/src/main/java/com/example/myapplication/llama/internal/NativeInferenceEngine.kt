package com.example.myapplication.llama.internal

import com.example.myapplication.llama.InferenceEngine
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flow

internal class NativeInferenceEngine : InferenceEngine {
    private val mutableState = MutableStateFlow<InferenceEngine.State>(InferenceEngine.State.Uninitialized)

    override val state: StateFlow<InferenceEngine.State> = mutableState.asStateFlow()

    override fun backendLabel(): String = NativeBridge.backendLabel()

    override fun isModelLoaded(): Boolean = NativeBridge.isModelLoaded()

    override fun loadedModelPath(): String = NativeBridge.loadedModelPath()

    override fun lastError(): String = NativeBridge.lastError()

    override suspend fun loadModel(pathToModel: String) {
        mutableState.value = InferenceEngine.State.LoadingModel
        val loaded = NativeBridge.loadModel(pathToModel)
        mutableState.value = if (loaded) {
            InferenceEngine.State.ModelReady
        } else {
            InferenceEngine.State.Error(NativeBridge.lastError())
        }
    }

    override suspend fun setSystemPrompt(systemPrompt: String) {
        if (!NativeBridge.isModelLoaded()) {
            val message = NativeBridge.lastError().ifBlank { "Load a model before setting the system prompt." }
            mutableState.value = InferenceEngine.State.Error(message)
            return
        }

        mutableState.value = InferenceEngine.State.ProcessingSystemPrompt
        val ok = NativeBridge.setSystemPrompt(systemPrompt)
        mutableState.value = if (ok) {
            InferenceEngine.State.ModelReady
        } else {
            InferenceEngine.State.Error(NativeBridge.lastError())
        }
    }

    override fun sendUserPrompt(message: String, predictLength: Int): Flow<String> = flow {
        if (!NativeBridge.isModelLoaded()) {
            val message = NativeBridge.lastError().ifBlank { "Load a model before generating." }
            mutableState.value = InferenceEngine.State.Error(message)
            return@flow
        }

        mutableState.value = InferenceEngine.State.ProcessingUserPrompt
        mutableState.value = InferenceEngine.State.Generating
        val output = NativeBridge.generate(message, predictLength)
        val error = NativeBridge.lastError()
        if (error.isNotBlank()) {
            mutableState.value = InferenceEngine.State.Error(error)
            return@flow
        }

        emit(output)
        mutableState.value = InferenceEngine.State.ModelReady
    }

    override suspend fun bench(pp: Int, tg: Int, pl: Int, nr: Int): String {
        if (!NativeBridge.isModelLoaded()) {
            val message = NativeBridge.lastError().ifBlank { "Load a model before benchmarking." }
            mutableState.value = InferenceEngine.State.Error(message)
            return message
        }

        mutableState.value = InferenceEngine.State.Benchmarking
        val output = NativeBridge.bench(pp, tg, pl, nr)
        val error = NativeBridge.lastError()
        mutableState.value = if (error.isBlank()) {
            InferenceEngine.State.ModelReady
        } else {
            InferenceEngine.State.Error(error)
        }
        return if (error.isBlank()) output else error
    }

    override fun cleanUp() {
        NativeBridge.unloadModel()
        mutableState.value = InferenceEngine.State.Uninitialized
    }

    override fun destroy() {
        NativeBridge.destroy()
        mutableState.value = InferenceEngine.State.Uninitialized
    }
}
