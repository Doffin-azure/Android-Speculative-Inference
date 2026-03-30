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

    override fun generate(prompt: String, maxTokens: Int): Flow<String> = flow {
        if (!NativeBridge.isModelLoaded()) {
            val message = NativeBridge.lastError().ifBlank { "Load a model before generating." }
            mutableState.value = InferenceEngine.State.Error(message)
            return@flow
        }

        mutableState.value = InferenceEngine.State.Generating
        val output = NativeBridge.generate(prompt, maxTokens)
        val error = NativeBridge.lastError()
        if (error.isNotBlank()) {
            mutableState.value = InferenceEngine.State.Error(error)
            return@flow
        }

        emit(output)
        mutableState.value = InferenceEngine.State.ModelReady
    }

    override fun unloadModel() {
        NativeBridge.unloadModel()
        mutableState.value = InferenceEngine.State.Uninitialized
    }
}
