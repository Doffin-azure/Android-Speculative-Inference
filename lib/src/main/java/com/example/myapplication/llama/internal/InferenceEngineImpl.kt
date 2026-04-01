package com.example.myapplication.llama.internal

import android.content.Context
import android.util.Log
import com.example.myapplication.llama.DraftSessionHandle
import com.example.myapplication.llama.DraftPathStep
import com.example.myapplication.llama.DraftPathStepCandidate
import com.example.myapplication.llama.DraftTreeNode
import com.example.myapplication.llama.DraftTreeProposal
import com.example.myapplication.llama.InferenceEngine
import dalvik.annotation.optimization.FastNative
import java.io.File
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.json.JSONObject

internal class InferenceEngineImpl private constructor(
    private val nativeLibDir: String
) : InferenceEngine {

    private data class DraftSessionRuntime(
        val sessionId: String,
        val systemPrompt: String,
        val userPrompt: String,
        val predictLength: Int,
        val acceptedText: String = "",
        val acceptedTokenIds: List<Int> = emptyList()
    )

    companion object {
        private const val TAG = "InferenceEngineImpl"

        @Volatile
        private var instance: InferenceEngine? = null

        internal fun getInstance(context: Context): InferenceEngine {
            return instance ?: synchronized(this) {
                instance ?: createInstance(context).also { instance = it }
            }
        }

        private fun createInstance(context: Context): InferenceEngineImpl {
            val nativeLibraryDir = context.applicationInfo.nativeLibraryDir
            require(nativeLibraryDir.isNotBlank()) { "Expected a valid native library path." }
            return InferenceEngineImpl(nativeLibraryDir)
        }
    }

    @FastNative
    private external fun init(nativeLibDir: String)

    @FastNative
    private external fun load(modelPath: String): Int

    @FastNative
    private external fun lastNativeLoadDiagnostics(): String

    @FastNative
    private external fun prepare(): Int

    @FastNative
    private external fun systemInfo(): String

    @FastNative
    private external fun benchModel(pp: Int, tg: Int, pl: Int, nr: Int): String

    @FastNative
    private external fun processSystemPrompt(systemPrompt: String): Int

    @FastNative
    private external fun processUserPrompt(userPrompt: String, predictLength: Int): Int

    @FastNative
    private external fun generateNextToken(): String?

    @FastNative
    private external fun resetDraftContext(
        systemPrompt: String,
        userPrompt: String,
        assistantText: String,
        predictLength: Int
    ): Int

    @FastNative
    private external fun generateDraftTokenIds(maxTokens: Int): IntArray

    @FastNative
    private external fun generateDraftTreeJson(maxDepth: Int, branchFactor: Int): String

    @FastNative
    private external fun renderTokenIds(tokenIds: IntArray): String

    @FastNative
    private external fun generateDraftRealTokenIds(maxTokens: Int): IntArray

    @FastNative
    private external fun generateDraftRealTokenTreeJson(maxDepth: Int, branchFactor: Int): String

    @FastNative
    private external fun unload()

    @FastNative
    private external fun shutdown()

    private fun describeLoadFailure(code: Int, modelPath: String): String {
        val file = File(modelPath)
        val sizeBytes = file.length()
        val sizeMb = sizeBytes / (1024 * 1024)
        val nativeDetails = runCatching { lastNativeLoadDiagnostics().trim() }.getOrDefault("")
        val detailSuffix = nativeDetails
            .takeIf { it.isNotBlank() }
            ?.let { " Native details: ${it.takeLast(600)}" }
            .orEmpty()
        return when (code) {
            1 -> "Failed to load model: native file open failed.$detailSuffix"
            2 -> "Failed to load model: imported file is empty.$detailSuffix"
            3 -> "Failed to load model: imported file is unexpectedly small (${sizeMb} MB).$detailSuffix"
            4 -> "Failed to load model: imported file does not begin with a valid GGUF header.$detailSuffix"
            5 -> "Failed to load model: GGUF header is valid, but Android llama.cpp could not create the model. This is likely an Android runtime/build compatibility issue.$detailSuffix"
            else -> "Failed to load model: $code.$detailSuffix"
        }
    }

    private val mutableState = MutableStateFlow<InferenceEngine.State>(InferenceEngine.State.Uninitialized)
    override val state: StateFlow<InferenceEngine.State> = mutableState.asStateFlow()

    private var currentModelPath = ""
    private var currentError = ""
    private var readyForSystemPrompt = false
    private val draftSessions = linkedMapOf<String, DraftSessionRuntime>()

    @Volatile
    private var cancelGeneration = false

    @OptIn(ExperimentalCoroutinesApi::class)
    private val llamaDispatcher = Dispatchers.IO.limitedParallelism(1)
    private val llamaScope = CoroutineScope(llamaDispatcher + SupervisorJob())

    init {
        llamaScope.launch {
            try {
                mutableState.value = InferenceEngine.State.Initializing
                System.loadLibrary("ai-chat")
                init(nativeLibDir)
                currentError = ""
                mutableState.value = InferenceEngine.State.Initialized
                Log.i(TAG, "Native engine initialized: ${systemInfo()}")
            } catch (e: Exception) {
                currentError = e.message ?: "Failed to initialize native engine."
                mutableState.value = InferenceEngine.State.Error(currentError)
                throw e
            } catch (e: UnsatisfiedLinkError) {
                currentError = e.message ?: "Failed to load ai-chat native library."
                mutableState.value = InferenceEngine.State.Error(currentError)
                throw e
            }
        }
    }

    private suspend fun awaitInitializedState() {
        val engineState = state.first {
            it is InferenceEngine.State.Initialized || it is InferenceEngine.State.Error
        }

        check(engineState is InferenceEngine.State.Initialized) {
            when (engineState) {
                is InferenceEngine.State.Error -> {
                    val detail = engineState.message.ifBlank { currentError }
                    "Engine initialization failed: ${detail.ifBlank { "unknown error" }}"
                }

                else -> "Engine is not ready yet: ${engineState.javaClass.simpleName}."
            }
        }
    }

    override fun backendLabel(): String = "ai-chat (official-style engine shell)"

    override fun isModelLoaded(): Boolean {
        return state.value is InferenceEngine.State.ModelReady ||
            state.value is InferenceEngine.State.Benchmarking ||
            state.value is InferenceEngine.State.ProcessingSystemPrompt ||
            state.value is InferenceEngine.State.ProcessingUserPrompt ||
            state.value is InferenceEngine.State.Generating
    }

    override fun loadedModelPath(): String = currentModelPath

    override fun lastError(): String = currentError

    override suspend fun loadModel(pathToModel: String) = withContext(llamaDispatcher) {
        awaitInitializedState()

        try {
            File(pathToModel).let {
                require(it.exists()) { "File not found." }
                require(it.isFile) { "Not a valid file." }
                require(it.canRead()) { "Cannot read file." }
            }

            mutableState.value = InferenceEngine.State.LoadingModel
            readyForSystemPrompt = false
            currentError = ""

            val loadResult = load(pathToModel)
            if (loadResult != 0) {
                throw IOException(describeLoadFailure(loadResult, pathToModel))
            }

            val prepareResult = prepare()
            if (prepareResult != 0) {
                throw IOException("Failed to prepare native resources: $prepareResult")
            }

            currentModelPath = pathToModel
            readyForSystemPrompt = true
            cancelGeneration = false
            mutableState.value = InferenceEngine.State.ModelReady
        } catch (e: Exception) {
            currentModelPath = ""
            currentError = e.message ?: "Error loading model."
            mutableState.value = InferenceEngine.State.Error(currentError)
            throw e
        }
    }

    override suspend fun setSystemPrompt(systemPrompt: String) = withContext(llamaDispatcher) {
        require(systemPrompt.isNotBlank()) { "Cannot process empty system prompt." }
        check(readyForSystemPrompt) { "System prompt must be set immediately after model load." }
        check(state.value is InferenceEngine.State.ModelReady) {
            "Cannot process system prompt in ${state.value.javaClass.simpleName}."
        }

        mutableState.value = InferenceEngine.State.ProcessingSystemPrompt
        val result = processSystemPrompt(systemPrompt)
        if (result != 0) {
            currentError = "Failed to process system prompt: $result"
            mutableState.value = InferenceEngine.State.Error(currentError)
            throw IOException(currentError)
        }

        currentError = ""
        readyForSystemPrompt = false
        mutableState.value = InferenceEngine.State.ModelReady
    }

    override fun sendUserPrompt(message: String, predictLength: Int): Flow<String> = flow {
        require(message.isNotBlank()) { "User prompt discarded due to being empty." }
        check(state.value is InferenceEngine.State.ModelReady) {
            "User prompt discarded due to: ${state.value.javaClass.simpleName}"
        }

        try {
            readyForSystemPrompt = false
            mutableState.value = InferenceEngine.State.ProcessingUserPrompt

            val processResult = processUserPrompt(message, predictLength)
            if (processResult != 0) {
                currentError = "Failed to process user prompt: $processResult"
                mutableState.value = InferenceEngine.State.Error(currentError)
                return@flow
            }

            currentError = ""
            mutableState.value = InferenceEngine.State.Generating
            while (!cancelGeneration) {
                val token = generateNextToken() ?: break
                if (token.isNotEmpty()) {
                    emit(token)
                }
            }
            mutableState.value = InferenceEngine.State.ModelReady
        } catch (e: CancellationException) {
            mutableState.value = InferenceEngine.State.ModelReady
            throw e
        } catch (e: Exception) {
            currentError = e.message ?: "Generation failed."
            mutableState.value = InferenceEngine.State.Error(currentError)
            throw e
        }
    }.flowOn(llamaDispatcher)

    override suspend fun bench(pp: Int, tg: Int, pl: Int, nr: Int): String = withContext(llamaDispatcher) {
        check(state.value is InferenceEngine.State.ModelReady) {
            "Benchmark request discarded due to: ${state.value.javaClass.simpleName}"
        }

        mutableState.value = InferenceEngine.State.Benchmarking
        val output = benchModel(pp, tg, pl, nr)
        currentError = ""
        mutableState.value = InferenceEngine.State.ModelReady
        output
    }

    override fun supportsDraftSession(): Boolean = true

    override fun supportsDraftTree(): Boolean = true

    override suspend fun startDraftSession(
        systemPrompt: String,
        userPrompt: String,
        predictLength: Int
    ): DraftSessionHandle = withContext(llamaDispatcher) {
        check(state.value is InferenceEngine.State.ModelReady) {
            "Cannot start draft session in ${state.value.javaClass.simpleName}."
        }

        val sessionId = UUID.randomUUID().toString()
        val runtime = DraftSessionRuntime(
            sessionId = sessionId,
            systemPrompt = systemPrompt,
            userPrompt = userPrompt,
            predictLength = predictLength
        )
        resetDraftRuntime(runtime)
        draftSessions[sessionId] = runtime
        DraftSessionHandle(
            sessionId = sessionId,
            runtimeLabel = "ai-chat draft session",
            acceptedText = runtime.acceptedText,
            acceptedTokenCount = runtime.acceptedText.codePointCount(0, runtime.acceptedText.length)
        )
    }

    override suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> = withContext(llamaDispatcher) {
        val runtime = draftSessions[sessionId]
            ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
        require(maxTokens > 0) { "maxTokens must be > 0." }
        resetDraftRuntime(runtime)
        generateDraftTokenIds(maxTokens).toList()
    }

    override suspend fun draftTreeProposal(
        sessionId: String,
        maxDepth: Int,
        branchFactor: Int
    ): DraftTreeProposal = withContext(llamaDispatcher) {
        val runtime = draftSessions[sessionId]
            ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
        require(maxDepth > 0) { "maxDepth must be > 0." }
        require(branchFactor > 0) { "branchFactor must be > 0." }
        resetDraftRuntime(runtime)
        parseDraftTreeProposalJson(
            sessionId = sessionId,
            rootAcceptedText = runtime.acceptedText,
            jsonText = generateDraftTreeJson(maxDepth, branchFactor)
        )
    }

    override suspend fun renderTokenIds(tokenIds: List<Int>): String = withContext(llamaDispatcher) {
        if (tokenIds.isEmpty()) {
            return@withContext ""
        }
        renderTokenIds(tokenIds.toIntArray())
    }

    override suspend fun draftNextRealTokenIds(sessionId: String, maxTokens: Int): List<Int> = withContext(llamaDispatcher) {
        val runtime = draftSessions[sessionId]
            ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
        require(maxTokens > 0) { "maxTokens must be > 0." }
        resetDraftRuntime(runtime)
        generateDraftRealTokenIds(maxTokens).toList()
    }

    override suspend fun draftRealTokenTreeProposal(
        sessionId: String,
        maxDepth: Int,
        branchFactor: Int
    ): DraftTreeProposal = withContext(llamaDispatcher) {
        val runtime = draftSessions[sessionId]
            ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
        require(maxDepth > 0) { "maxDepth must be > 0." }
        require(branchFactor > 0) { "branchFactor must be > 0." }
        resetDraftRuntime(runtime)
        parseDraftTreeProposalJson(
            sessionId = sessionId,
            rootAcceptedText = runtime.acceptedText,
            jsonText = generateDraftRealTokenTreeJson(maxDepth, branchFactor)
        )
    }

    override suspend fun applyVerifiedRealTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle = withContext(llamaDispatcher) {
        val runtime = draftSessions[sessionId]
            ?: throw IllegalArgumentException("Unknown draft session: $sessionId")

        val safeTokenIds = tokenIds.filter { it >= 0 }
        val updatedTokenIds = runtime.acceptedTokenIds + safeTokenIds
        val updatedText = if (updatedTokenIds.isEmpty()) {
            ""
        } else {
            renderTokenIds(updatedTokenIds.toIntArray())
        }
        val updatedRuntime = runtime.copy(
            acceptedText = updatedText,
            acceptedTokenIds = updatedTokenIds
        )
        resetDraftRuntime(updatedRuntime)
        draftSessions[sessionId] = updatedRuntime
        DraftSessionHandle(
            sessionId = updatedRuntime.sessionId,
            runtimeLabel = "ai-chat draft session",
            acceptedText = updatedRuntime.acceptedText,
            acceptedTokenCount = updatedRuntime.acceptedTokenIds.size
        )
    }

    override suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle = withContext(llamaDispatcher) {
        val runtime = draftSessions[sessionId]
            ?: throw IllegalArgumentException("Unknown draft session: $sessionId")

        val appendedText = codePointIdsToString(tokenIds)
        val updatedRuntime = runtime.copy(acceptedText = runtime.acceptedText + appendedText)
        resetDraftRuntime(updatedRuntime)
        draftSessions[sessionId] = updatedRuntime
        DraftSessionHandle(
            sessionId = updatedRuntime.sessionId,
            runtimeLabel = "ai-chat draft session",
            acceptedText = updatedRuntime.acceptedText,
            acceptedTokenCount = updatedRuntime.acceptedText.codePointCount(0, updatedRuntime.acceptedText.length)
        )
    }

    override suspend fun closeDraftSession(sessionId: String) {
        withContext(llamaDispatcher) {
            draftSessions.remove(sessionId)
        }
    }

    private fun codePointIdsToString(tokenIds: List<Int>): String {
        if (tokenIds.isEmpty()) {
            return ""
        }
        val builder = StringBuilder()
        tokenIds.filter { it >= 0 }.forEach { codePoint ->
            builder.appendCodePoint(codePoint)
        }
        return builder.toString()
    }

    private fun resetDraftRuntime(runtime: DraftSessionRuntime) {
        val result = resetDraftContext(
            systemPrompt = runtime.systemPrompt,
            userPrompt = runtime.userPrompt,
            assistantText = runtime.acceptedText,
            predictLength = runtime.predictLength
        )
        if (result != 0) {
            currentError = "Failed to reset draft runtime: $result"
            throw IOException(currentError)
        }
    }

    private fun parseDraftTreeProposalJson(
        sessionId: String,
        rootAcceptedText: String,
        jsonText: String
    ): DraftTreeProposal {
        val json = JSONObject(jsonText)
        val bestPathTokenIds = mutableListOf<Int>()
        val bestPathArray = json.optJSONArray("bestPathTokenIds")
        if (bestPathArray != null) {
            for (index in 0 until bestPathArray.length()) {
                bestPathTokenIds += bestPathArray.optInt(index)
            }
        }
        val bestPathNodeIndices = mutableListOf<Int>()
        val bestPathNodeArray = json.optJSONArray("bestPathNodeIndices")
        if (bestPathNodeArray != null) {
            for (index in 0 until bestPathNodeArray.length()) {
                bestPathNodeIndices += bestPathNodeArray.optInt(index)
            }
        }

        val nodes = mutableListOf<DraftTreeNode>()
        val nodesArray = json.optJSONArray("nodes")
        if (nodesArray != null) {
            for (index in 0 until nodesArray.length()) {
                val node = nodesArray.optJSONObject(index) ?: continue
                nodes += DraftTreeNode(
                    nodeIndex = node.optInt("nodeIndex", index),
                    tokenId = node.optInt("tokenId"),
                    tokenText = node.optString("tokenText"),
                    depth = node.optInt("depth"),
                    parentNodeIndex = node.optInt("parentNodeIndex", -1),
                    probability = node.optDouble("probability", 0.0).toFloat(),
                    logProbability = node.optDouble("logProbability", Double.NEGATIVE_INFINITY).toFloat(),
                    cumulativeLogProbability = node.optDouble(
                        "cumulativeLogProbability",
                        node.optDouble("logProbability", Double.NEGATIVE_INFINITY)
                    ).toFloat()
                )
            }
        }

        val draftPathSteps = mutableListOf<DraftPathStep>()
        val draftPathStepsArray = json.optJSONArray("draftPathSteps")
        if (draftPathStepsArray != null) {
            for (index in 0 until draftPathStepsArray.length()) {
                val step = draftPathStepsArray.optJSONObject(index) ?: continue
                val acceptedPrefixTokenIds = mutableListOf<Int>()
                val acceptedPrefixArray = step.optJSONArray("acceptedPrefixTokenIds")
                if (acceptedPrefixArray != null) {
                    for (tokenIndex in 0 until acceptedPrefixArray.length()) {
                        acceptedPrefixTokenIds += acceptedPrefixArray.optInt(tokenIndex)
                    }
                }
                val candidates = mutableListOf<DraftPathStepCandidate>()
                val candidatesArray = step.optJSONArray("candidates")
                if (candidatesArray != null) {
                    for (candidateIndex in 0 until candidatesArray.length()) {
                        val candidate = candidatesArray.optJSONObject(candidateIndex) ?: continue
                        candidates += DraftPathStepCandidate(
                            nodeIndex = candidate.optInt("nodeIndex", -1),
                            tokenId = candidate.optInt("tokenId", -1),
                            tokenText = candidate.optString("tokenText"),
                            probability = candidate.optDouble("probability", 0.0).toFloat(),
                            logProbability = candidate.optDouble(
                                "logProbability",
                                Double.NEGATIVE_INFINITY
                            ).toFloat()
                        )
                    }
                }
                draftPathSteps += DraftPathStep(
                    depth = step.optInt("depth", index),
                    parentNodeIndex = step.optInt("parentNodeIndex", -1),
                    acceptedPrefixTokenIds = acceptedPrefixTokenIds,
                    candidates = candidates,
                    bestTokenId = step.optInt("bestTokenId", -1),
                    bestNodeIndex = step.optInt("bestNodeIndex", -1)
                )
            }
        }

        return DraftTreeProposal(
            sessionId = sessionId,
            tokenMode = json.optString("tokenMode", "codepoint_legacy"),
            rootAcceptedText = rootAcceptedText,
            bestPathTokenIds = bestPathTokenIds,
            bestPathNodeIndices = bestPathNodeIndices,
            bestPathText = json.optString("bestPathText"),
            branchFactor = json.optInt("branchFactor"),
            depthEvaluated = json.optInt("depthEvaluated"),
            nodeCount = json.optInt("nodeCount", nodes.size),
            nodes = nodes,
            draftPathSteps = draftPathSteps
        )
    }

    override fun cleanUp() {
        cancelGeneration = true
        runBlocking(llamaDispatcher) {
            when (state.value) {
                is InferenceEngine.State.ModelReady,
                is InferenceEngine.State.Benchmarking,
                is InferenceEngine.State.Error -> {
                    mutableState.value = InferenceEngine.State.UnloadingModel
                    unload()
                    currentModelPath = ""
                    currentError = ""
                    readyForSystemPrompt = false
                    draftSessions.clear()
                    mutableState.value = InferenceEngine.State.Initialized
                }

                is InferenceEngine.State.Initialized,
                is InferenceEngine.State.Initializing,
                is InferenceEngine.State.Uninitialized -> Unit

                else -> {
                    currentModelPath = ""
                    currentError = ""
                    readyForSystemPrompt = false
                    draftSessions.clear()
                    mutableState.value = InferenceEngine.State.Initialized
                }
            }
        }
    }

    override fun destroy() {
        cancelGeneration = true
        runBlocking(llamaDispatcher) {
            readyForSystemPrompt = false
            when (state.value) {
                is InferenceEngine.State.Uninitialized -> Unit
                is InferenceEngine.State.Initialized -> shutdown()
                else -> {
                    unload()
                    shutdown()
                }
            }
            currentModelPath = ""
            currentError = ""
            draftSessions.clear()
            mutableState.value = InferenceEngine.State.Uninitialized
        }
        llamaScope.cancel()
    }
}
