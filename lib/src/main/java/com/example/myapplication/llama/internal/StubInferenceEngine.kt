package com.example.myapplication.llama.internal

import com.example.myapplication.llama.InferenceEngine
import java.io.File
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flow

class StubInferenceEngine : InferenceEngine {
    private val mutableState = MutableStateFlow<InferenceEngine.State>(InferenceEngine.State.Uninitialized)
    private var loadedModelPath = ""
    private var lastError = "No model loaded."

    override val state: StateFlow<InferenceEngine.State> = mutableState.asStateFlow()

    override fun backendLabel(): String = "lib-stub (landing zone for llama.cpp module)"

    override fun isModelLoaded(): Boolean {
        return state.value is InferenceEngine.State.ModelReady ||
            state.value is InferenceEngine.State.Generating
    }

    override fun loadedModelPath(): String = loadedModelPath

    override fun lastError(): String = lastError

    override suspend fun loadModel(pathToModel: String) {
        mutableState.value = InferenceEngine.State.LoadingModel

        when {
            pathToModel.isBlank() -> {
                loadedModelPath = ""
                lastError = "Model path is empty."
                mutableState.value = InferenceEngine.State.Error(lastError)
            }

            !File(pathToModel).exists() -> {
                loadedModelPath = ""
                lastError = "Model file does not exist: $pathToModel"
                mutableState.value = InferenceEngine.State.Error(lastError)
            }

            else -> {
                loadedModelPath = pathToModel
                lastError = ""
                mutableState.value = InferenceEngine.State.ModelReady
            }
        }
    }

    override fun generate(prompt: String, maxTokens: Int): Flow<String> = flow {
        if (state.value !is InferenceEngine.State.ModelReady) {
            lastError = "Load a model before generating."
            mutableState.value = InferenceEngine.State.Error(lastError)
            return@flow
        }

        if (prompt.isBlank()) {
            lastError = "Prompt is empty."
            mutableState.value = InferenceEngine.State.Error(lastError)
            return@flow
        }

        mutableState.value = InferenceEngine.State.Generating
        lastError = ""
        emit("[stub-lib] model=$loadedModelPath maxTokens=$maxTokens prompt=$prompt")
        mutableState.value = InferenceEngine.State.ModelReady
    }

    override fun unloadModel() {
        loadedModelPath = ""
        lastError = "No model loaded."
        mutableState.value = InferenceEngine.State.Uninitialized
    }
}
