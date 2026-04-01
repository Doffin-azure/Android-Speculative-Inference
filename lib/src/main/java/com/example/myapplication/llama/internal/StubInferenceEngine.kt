package com.example.myapplication.llama.internal

import com.example.myapplication.llama.InferenceEngine
import com.example.myapplication.llama.DraftTreeProposal
import com.example.myapplication.llama.DraftTreeNode
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
    private var systemPrompt = ""

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
                systemPrompt = ""
                mutableState.value = InferenceEngine.State.ModelReady
            }
        }
    }

    override suspend fun setSystemPrompt(systemPrompt: String) {
        if (!isModelLoaded()) {
            lastError = "Load a model before setting the system prompt."
            mutableState.value = InferenceEngine.State.Error(lastError)
            return
        }

        mutableState.value = InferenceEngine.State.ProcessingSystemPrompt
        this.systemPrompt = systemPrompt
        lastError = ""
        mutableState.value = InferenceEngine.State.ModelReady
    }

    override fun sendUserPrompt(message: String, predictLength: Int): Flow<String> = flow {
        if (state.value !is InferenceEngine.State.ModelReady) {
            lastError = "Load a model before generating."
            mutableState.value = InferenceEngine.State.Error(lastError)
            return@flow
        }

        if (message.isBlank()) {
            lastError = "Prompt is empty."
            mutableState.value = InferenceEngine.State.Error(lastError)
            return@flow
        }

        mutableState.value = InferenceEngine.State.ProcessingUserPrompt
        mutableState.value = InferenceEngine.State.Generating
        lastError = ""
        val systemPromptSuffix = if (systemPrompt.isBlank()) "" else " systemPrompt=$systemPrompt"
        emit("[stub-lib] model=$loadedModelPath predictLength=$predictLength prompt=$message$systemPromptSuffix")
        mutableState.value = InferenceEngine.State.ModelReady
    }

    override suspend fun bench(pp: Int, tg: Int, pl: Int, nr: Int): String {
        if (!isModelLoaded()) {
            lastError = "Load a model before benchmarking."
            mutableState.value = InferenceEngine.State.Error(lastError)
            return lastError
        }

        mutableState.value = InferenceEngine.State.Benchmarking
        lastError = ""
        val result = "[stub-bench] pp=$pp tg=$tg pl=$pl nr=$nr model=$loadedModelPath"
        mutableState.value = InferenceEngine.State.ModelReady
        return result
    }

    override fun cleanUp() {
        loadedModelPath = ""
        lastError = "No model loaded."
        systemPrompt = ""
        mutableState.value = InferenceEngine.State.Uninitialized
    }

    override suspend fun draftTreeProposal(
        sessionId: String,
        maxDepth: Int,
        branchFactor: Int
    ): DraftTreeProposal {
        return DraftTreeProposal(
            sessionId = sessionId,
            tokenMode = "codepoint_legacy",
            rootAcceptedText = "",
            bestPathTokenIds = emptyList(),
            bestPathNodeIndices = emptyList(),
            bestPathText = "",
            branchFactor = branchFactor,
            depthEvaluated = 0,
            nodeCount = 0,
            nodes = emptyList()
        )
    }

    override suspend fun renderTokenIds(tokenIds: List<Int>): String {
        if (tokenIds.isEmpty()) {
            return ""
        }
        return tokenIds.joinToString(separator = " ") { it.toString() }
    }

    override suspend fun draftNextRealTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        return emptyList()
    }

    override suspend fun draftRealTokenTreeProposal(
        sessionId: String,
        maxDepth: Int,
        branchFactor: Int
    ): DraftTreeProposal {
        return draftTreeProposal(sessionId, maxDepth, branchFactor)
    }

    override suspend fun applyVerifiedRealTokens(sessionId: String, tokenIds: List<Int>): com.example.myapplication.llama.DraftSessionHandle {
        throw UnsupportedOperationException("StubInferenceEngine does not keep real-token draft sessions.")
    }

    override fun destroy() {
        cleanUp()
    }
}
