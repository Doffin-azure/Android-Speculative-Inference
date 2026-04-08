package com.example.myapplication.llama

import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.StateFlow

data class DraftSessionHandle(
    val sessionId: String,
    val runtimeLabel: String,
    val acceptedText: String = "",
    val acceptedTokenCount: Int = 0
)

data class DraftTreeNode(
    val nodeIndex: Int,
    val tokenId: Int,
    val tokenText: String,
    val depth: Int,
    val parentNodeIndex: Int,
    val probability: Float,
    val logProbability: Float,
    val cumulativeLogProbability: Float
)

data class DraftPathStepCandidate(
    val nodeIndex: Int,
    val tokenId: Int,
    val tokenText: String,
    val probability: Float,
    val logProbability: Float
)

data class DraftPathStep(
    val depth: Int,
    val parentNodeIndex: Int,
    val acceptedPrefixTokenIds: List<Int>,
    val candidates: List<DraftPathStepCandidate>,
    val bestTokenId: Int,
    val bestNodeIndex: Int
)

data class DraftTreeProposal(
    val sessionId: String,
    val tokenMode: String,
    val rootAcceptedText: String,
    val bestPathTokenIds: List<Int>,
    val bestPathNodeIndices: List<Int>,
    val bestPathText: String,
    val branchFactor: Int,
    val depthEvaluated: Int,
    val nodeCount: Int,
    val nodes: List<DraftTreeNode>,
    val draftPathSteps: List<DraftPathStep> = emptyList()
)

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

    fun supportsDraftSession(): Boolean = false

    fun supportsSplitDraftControl(): Boolean = false

    fun supportsDraftTree(): Boolean = false

    suspend fun startDraftSession(
        systemPrompt: String,
        userPrompt: String,
        predictLength: Int = DEFAULT_PREDICT_LENGTH
    ): DraftSessionHandle {
        throw UnsupportedOperationException("Draft session is not implemented by this engine.")
    }

    suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        throw UnsupportedOperationException("Draft token generation is not implemented by this engine.")
    }

    suspend fun draftTreeProposal(
        sessionId: String,
        maxDepth: Int,
        branchFactor: Int
    ): DraftTreeProposal {
        throw UnsupportedOperationException("Draft tree generation is not implemented by this engine.")
    }

    suspend fun renderTokenIds(tokenIds: List<Int>): String {
        throw UnsupportedOperationException("Token rendering is not implemented by this engine.")
    }

    suspend fun draftNextRealTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        throw UnsupportedOperationException("Real-token draft generation is not implemented by this engine.")
    }

    suspend fun syncAndDraftNextRealTokenIds(
        sessionId: String,
        authoritativeTokenIds: List<Int>,
        maxTokens: Int
    ): List<Int> {
        throw UnsupportedOperationException("Combined split draft synchronization/generation is not implemented by this engine.")
    }

    suspend fun syncRealTokenDraftSession(sessionId: String, authoritativeTokenIds: List<Int>): DraftSessionHandle {
        throw UnsupportedOperationException("Split draft synchronization is not implemented by this engine.")
    }

    suspend fun draftRealTokenTreeProposal(
        sessionId: String,
        maxDepth: Int,
        branchFactor: Int
    ): DraftTreeProposal {
        throw UnsupportedOperationException("Real-token draft tree generation is not implemented by this engine.")
    }

    suspend fun applyVerifiedRealTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle {
        throw UnsupportedOperationException("Applying verified real tokens is not implemented by this engine.")
    }

    suspend fun applyVerifiedRealTokensAndDraftNextRealTokenIds(
        sessionId: String,
        tokenIds: List<Int>,
        maxTokens: Int
    ): List<Int> {
        throw UnsupportedOperationException("Combined real-token apply/draft is not implemented by this engine.")
    }

    suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle {
        throw UnsupportedOperationException("Applying verified tokens is not implemented by this engine.")
    }

    suspend fun closeDraftSession(sessionId: String) {
    }

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
