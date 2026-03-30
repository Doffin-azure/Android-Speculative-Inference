package com.example.myapplication.llama.internal

import android.content.Context
import android.util.Log
import com.example.myapplication.llama.InferenceEngine
import dalvik.annotation.optimization.FastNative
import java.io.File
import java.io.IOException
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

internal class InferenceEngineImpl private constructor(
    private val nativeLibDir: String
) : InferenceEngine {

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
    private external fun unload()

    @FastNative
    private external fun shutdown()

    private val mutableState = MutableStateFlow<InferenceEngine.State>(InferenceEngine.State.Uninitialized)
    override val state: StateFlow<InferenceEngine.State> = mutableState.asStateFlow()

    private var currentModelPath = ""
    private var currentError = ""
    private var readyForSystemPrompt = false

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
                throw IOException("Failed to load model: $loadResult")
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
                    mutableState.value = InferenceEngine.State.Initialized
                }

                is InferenceEngine.State.Initialized,
                is InferenceEngine.State.Initializing,
                is InferenceEngine.State.Uninitialized -> Unit

                else -> {
                    currentModelPath = ""
                    currentError = ""
                    readyForSystemPrompt = false
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
            mutableState.value = InferenceEngine.State.Uninitialized
        }
        llamaScope.cancel()
    }
}
