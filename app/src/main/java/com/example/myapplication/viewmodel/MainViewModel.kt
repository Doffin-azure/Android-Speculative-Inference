package com.example.myapplication.viewmodel

import android.app.Application
import android.content.Intent
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.documentfile.provider.DocumentFile
import com.example.myapplication.inference.LocalLlm
import com.example.myapplication.inference.LocalLlmImpl
import com.example.myapplication.inference.RemoteGenerateRequest
import com.example.myapplication.inference.RemoteInferenceClient
import com.example.myapplication.inference.SpeculativeCloseRequest
import com.example.myapplication.inference.SpeculativeProposeRequest
import com.example.myapplication.inference.SpeculativeStartRequest
import com.example.myapplication.llama.DraftSessionHandle
import com.example.myapplication.llama.DraftTreeProposal
import com.example.myapplication.llama.debug.DraftRuntimeProbeDemo
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File
import java.io.RandomAccessFile
import java.util.UUID

class MainViewModel(
    application: Application
) : AndroidViewModel(application) {

    data class SpeculativeStepTrace(
        val draftStep: Int,
        val proposedTokenIds: List<Int>,
        val proposedText: String,
        val draftFetchMs: Long,
        val remoteProposeMs: Long,
        val localApplyMs: Long,
        val tokenMode: String,
        val acceptanceMode: String,
        val acceptedCount: Int,
        val acceptedTokenIds: List<Int>,
        val rejectedFromIndex: Int,
        val correctionTokenIds: List<Int>,
        val targetTextDelta: String,
        val acceptedText: String,
        val lastReplayPrompt: String,
        val verifierStage: String,
        val trueRuntimeBackend: String,
        val llamaServerSlotId: Int,
        val lastTrueChunkStart: Int,
        val lastTrueChunkConsumed: Int,
        val trueCacheHitStreak: Int,
        val trueFetchStreak: Int,
        val treeCandidateCount: Int,
        val treeBestPathTokenIds: List<Int>,
        val treeBranchFactor: Int,
        val treeDepthEvaluated: Int,
        val treeDebugSummary: String,
        val timingPrepareMs: Double,
        val timingDecodeMs: Double,
        val timingSampleMs: Double,
        val timingRollbackMs: Double,
        val timingHelperTotalMs: Double,
        val timingHelperRoundTripMs: Double,
        val timingServiceTotalMs: Double,
        val draftTreeNodeCount: Int,
        val draftTreeDepthEvaluated: Int,
        val draftTreeBestPathNodeIndices: List<Int>,
        val status: String,
        val finishReason: String
    )

    enum class InferenceMode {
        LOCAL,
        REMOTE,
        SPECULATIVE
    }

    data class ModelCandidate(
        val name: String,
        val contentUri: String,
        val sizeBytes: Long
    )

    companion object {
        private const val SPECULATIVE_TEST_MAX_STEPS = 128
        private const val SPECULATIVE_TEST_MAX_DRAFT_TOKENS = 16
        private const val SPECULATIVE_TEST_MIN_DRAFT_TOKENS = 4
    }

    private val localLlm: LocalLlm = LocalLlmImpl(application.applicationContext)
    private val draftRuntimeProbeDemo = DraftRuntimeProbeDemo(application.applicationContext)
    private val remoteClient = RemoteInferenceClient()

    private val _backendLabel = MutableStateFlow("Detecting backend...")
    val backendLabel: StateFlow<String> = _backendLabel.asStateFlow()

    private val _inferenceMode = MutableStateFlow(InferenceMode.LOCAL)
    val inferenceMode: StateFlow<InferenceMode> = _inferenceMode.asStateFlow()

    private val _remoteServerUrl = MutableStateFlow("http://10.27.36.14:8080")
    val remoteServerUrl: StateFlow<String> = _remoteServerUrl.asStateFlow()

    private val _output = MutableStateFlow("Ready")
    val output: StateFlow<String> = _output.asStateFlow()

    private val _statusMessage = MutableStateFlow("Idle")
    val statusMessage: StateFlow<String> = _statusMessage.asStateFlow()

    private val _eventLog = MutableStateFlow("Ready")
    val eventLog: StateFlow<String> = _eventLog.asStateFlow()

    private val _diagnosticLogPath = MutableStateFlow("")
    val diagnosticLogPath: StateFlow<String> = _diagnosticLogPath.asStateFlow()

    private val _isModelLoaded = MutableStateFlow(false)
    val isModelLoaded: StateFlow<Boolean> = _isModelLoaded.asStateFlow()

    private val _modelPath = MutableStateFlow("")
    val modelPath: StateFlow<String> = _modelPath.asStateFlow()

    private val _selectedModelContentUri = MutableStateFlow("")

    private val _modelCandidates = MutableStateFlow<List<ModelCandidate>>(emptyList())
    val modelCandidates: StateFlow<List<ModelCandidate>> = _modelCandidates.asStateFlow()

    private val _loadedModelPath = MutableStateFlow("")
    val loadedModelPath: StateFlow<String> = _loadedModelPath.asStateFlow()

    private val _remoteBackendLabel = MutableStateFlow("")
    val remoteBackendLabel: StateFlow<String> = _remoteBackendLabel.asStateFlow()

    private val _remoteProbeSummary = MutableStateFlow("")
    val remoteProbeSummary: StateFlow<String> = _remoteProbeSummary.asStateFlow()

    private val _remoteResultSummary = MutableStateFlow("")
    val remoteResultSummary: StateFlow<String> = _remoteResultSummary.asStateFlow()

    private val _speculativeSessionSummary = MutableStateFlow("")
    val speculativeSessionSummary: StateFlow<String> = _speculativeSessionSummary.asStateFlow()

    private val _speculativeForceMismatch = MutableStateFlow(false)
    val speculativeForceMismatch: StateFlow<Boolean> = _speculativeForceMismatch.asStateFlow()

    private val _speculativeVerifierMode = MutableStateFlow("")
    val speculativeVerifierMode: StateFlow<String> = _speculativeVerifierMode.asStateFlow()

    private val _lastError = MutableStateFlow("")
    val lastError: StateFlow<String> = _lastError.asStateFlow()

    private val _isLoadingModel = MutableStateFlow(false)
    val isLoadingModel: StateFlow<Boolean> = _isLoadingModel.asStateFlow()

    private val _isGenerating = MutableStateFlow(false)
    val isGenerating: StateFlow<Boolean> = _isGenerating.asStateFlow()

    init {
        _diagnosticLogPath.value = diagnosticLogFile().absolutePath
        _backendLabel.value = try {
            localLlm.backendLabel()
        } catch (e: Exception) {
            "Backend unavailable: ${e.message ?: "unknown error"}"
        }

        appendLog("Backend: ${_backendLabel.value}")
        refreshNativeState()
    }

    fun setInferenceMode(mode: InferenceMode) {
        _inferenceMode.value = mode
        _statusMessage.value = when (mode) {
            InferenceMode.LOCAL -> "Local inference mode selected."
            InferenceMode.REMOTE -> "Remote inference mode selected."
            InferenceMode.SPECULATIVE -> "Speculative inference mode selected."
        }
        appendLog("Inference mode changed to ${mode.name}.")
    }

    fun setRemoteServerUrl(url: String) {
        _remoteServerUrl.value = url
    }

    fun setSpeculativeForceMismatch(enabled: Boolean) {
        _speculativeForceMismatch.value = enabled
        appendLog("Speculative force mismatch set to $enabled.")
    }

    fun onModelDirectorySelected(directoryUri: Uri) {
        val application = getApplication<Application>()
        runCatching {
            application.contentResolver.takePersistableUriPermission(
                directoryUri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION
            )
        }

        val modelFiles = findModelFilesInDirectory(directoryUri)
        if (modelFiles.isEmpty()) {
            _modelCandidates.value = emptyList()
            _selectedModelContentUri.value = ""
            _modelPath.value = ""
            _statusMessage.value = "No .gguf model found in selected directory."
            _lastError.value = "Selected directory does not contain a readable .gguf file."
            appendLog("Directory selection failed: no readable .gguf file found.")
            return
        }

        _modelCandidates.value = modelFiles
        selectModelCandidate(
            path = modelFiles.first().contentUri,
            announceChoice = modelFiles.size == 1
        )
        _statusMessage.value = if (modelFiles.size == 1) {
            "Model selected from directory."
        } else {
            "Multiple models found. Pick the one to load."
        }
        _lastError.value = ""
        appendLog("Selected directory with ${modelFiles.size} model candidate(s).")
    }

    fun selectModelCandidate(path: String, announceChoice: Boolean = true) {
        val selected = _modelCandidates.value.firstOrNull { it.contentUri == path } ?: return
        _selectedModelContentUri.value = selected.contentUri
        _modelPath.value = selected.name
        if (announceChoice) {
            _statusMessage.value = "Selected model: ${selected.name}"
            _lastError.value = ""
        }
        appendLog("Model candidate selected: ${selected.name} (${selected.sizeBytes} bytes)")
    }

    fun loadModel() {
        viewModelScope.launch {
            if (_isLoadingModel.value || _isGenerating.value) {
                return@launch
            }

            if (_modelPath.value.isBlank()) {
                _statusMessage.value = "Pick a model directory first."
                _lastError.value = "Model path is empty."
                appendLog("Load blocked: model path is empty.")
                return@launch
            }

            _isLoadingModel.value = true
            _statusMessage.value = "Loading model..."
            _lastError.value = ""
            try {
                val selectedModel = _modelCandidates.value.firstOrNull {
                    it.contentUri == _selectedModelContentUri.value
                }
                requireNotNull(selectedModel) { "No model file is currently selected." }
                appendLog("Load requested for ${selectedModel.name} (${selectedModel.sizeBytes} bytes)")

                _statusMessage.value = "Preparing readable local model copy..."
                val readableModelFile = ensureReadableLocalModelCopy(selectedModel)
                appendLog("Prepared local copy: ${readableModelFile.absolutePath} (${readableModelFile.length()} bytes)")

                _statusMessage.value = "Loading model..."
                val ok = localLlm.loadModel(readableModelFile.absolutePath)
                refreshNativeState()
                _statusMessage.value = if (ok) {
                    "Model loaded."
                } else {
                    "Model load failed."
                }
                appendLog(
                    if (ok) {
                        "Model loaded successfully."
                    } else {
                        "Model load returned false. Last error: ${_lastError.value}"
                    }
                )
            } catch (e: Exception) {
                _isModelLoaded.value = false
                _loadedModelPath.value = ""
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Load error: ${e.message}"
                appendLog("Load error: ${e.message ?: "unknown error"}")
            } finally {
                _isLoadingModel.value = false
            }
        }
    }

    fun runLocal(prompt: String) {
        viewModelScope.launch {
            if (_isLoadingModel.value || _isGenerating.value) {
                return@launch
            }

            if (!_isModelLoaded.value) {
                _statusMessage.value = "Load model first."
                appendLog("Run blocked: model not loaded.")
                return@launch
            }

            if (prompt.isBlank()) {
                _statusMessage.value = "Please enter a prompt."
                appendLog("Run blocked: prompt is empty.")
                return@launch
            }

            _isGenerating.value = true
            _statusMessage.value = "Running..."
            _lastError.value = ""
            try {
                appendLog("Generation requested. Prompt length: ${prompt.length}")
                val localRunStartedAt = System.currentTimeMillis()
                _output.value = localLlm.generate(prompt)
                val localRunMs = System.currentTimeMillis() - localRunStartedAt
                refreshNativeState()
                _statusMessage.value = "Inference complete."
                appendLog("Generation completed in ${formatDurationMs(localRunMs)}. Output length: ${_output.value.length}")
            } catch (e: Exception) {
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Run error: ${e.message}"
                appendLog("Run error: ${e.message ?: "unknown error"}")
            } finally {
                _isGenerating.value = false
            }
        }
    }

    fun runInference(prompt: String) {
        when (_inferenceMode.value) {
            InferenceMode.LOCAL -> runLocal(prompt)
            InferenceMode.REMOTE -> runRemote(prompt)
            InferenceMode.SPECULATIVE -> runSpeculative(prompt)
        }
    }

    fun runDraftRuntimeProbeDemo(prompt: String) {
        viewModelScope.launch {
            if (_isLoadingModel.value || _isGenerating.value) {
                return@launch
            }

            if (!_isModelLoaded.value || _loadedModelPath.value.isBlank()) {
                _statusMessage.value = "Load model first."
                appendLog("Draft runtime probe blocked: model not loaded.")
                return@launch
            }

            if (prompt.isBlank()) {
                _statusMessage.value = "Please enter a prompt."
                appendLog("Draft runtime probe blocked: prompt is empty.")
                return@launch
            }

            _isGenerating.value = true
            _statusMessage.value = "Running draft runtime probe..."
            _lastError.value = ""
            try {
                appendLog("Draft runtime probe requested. Prompt length: ${prompt.length}")
                val result = draftRuntimeProbeDemo.runTopKAndStateRoundTripDemo(
                    modelPath = _loadedModelPath.value,
                    userPrompt = prompt
                )
                _output.value = result
                _statusMessage.value = "Draft runtime probe complete."
                appendLog("Draft runtime probe completed.")
            } catch (e: Exception) {
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Draft runtime probe error: ${e.message}"
                appendLog("Draft runtime probe error: ${e.message ?: "unknown error"}")
            } finally {
                _isGenerating.value = false
                persistDiagnosticSnapshot()
            }
        }
    }

    fun testRemoteConnectivity() {
        viewModelScope.launch {
            if (_isLoadingModel.value || _isGenerating.value) {
                return@launch
            }

            val baseUrl = _remoteServerUrl.value.trim()
            if (baseUrl.isBlank()) {
                _statusMessage.value = "Enter a remote service URL."
                _lastError.value = "Remote service URL is empty."
                appendLog("Remote probe blocked: remote service URL is empty.")
                return@launch
            }

            _isGenerating.value = true
            _statusMessage.value = "Testing remote connectivity..."
            _lastError.value = ""
            _remoteProbeSummary.value = ""
            _remoteResultSummary.value = ""

            try {
                appendLog("Remote probe requested for $baseUrl")
                val probe = remoteClient.probe(baseUrl)
                _speculativeVerifierMode.value = probe.speculativeVerifierMode
                val summary = buildString {
                    appendLine("Probe status: ${probe.status}")
                    appendLine("Message: ${probe.message}")
                    appendLine("Server saw client as: ${probe.clientAddress}")
                    appendLine("Desktop request log: ${probe.requestLogPath}")
                    appendLine("Desktop IPv4 addresses: ${probe.ipv4Addresses.joinToString()}")
                    appendLine("Speculative verifier mode: ${probe.speculativeVerifierMode}")
                }.trim()
                _remoteProbeSummary.value = summary
                _output.value = summary
                _statusMessage.value = "Remote connectivity probe succeeded."
                appendLog("Remote probe succeeded. Server saw client as ${probe.clientAddress}")
            } catch (e: Exception) {
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Remote probe error: ${e.message}"
                _remoteProbeSummary.value = ""
                appendLog("Remote probe error: ${e.message ?: "unknown error"}")
            } finally {
                _isGenerating.value = false
                persistDiagnosticSnapshot()
            }
        }
    }

    private fun runRemote(prompt: String) {
        viewModelScope.launch {
            if (_isLoadingModel.value || _isGenerating.value) {
                return@launch
            }

            if (prompt.isBlank()) {
                _statusMessage.value = "Please enter a prompt."
                appendLog("Remote run blocked: prompt is empty.")
                return@launch
            }

            val baseUrl = _remoteServerUrl.value.trim()
            if (baseUrl.isBlank()) {
                _statusMessage.value = "Enter a remote service URL."
                _lastError.value = "Remote service URL is empty."
                appendLog("Remote run blocked: remote service URL is empty.")
                return@launch
            }

            _isGenerating.value = true
            _statusMessage.value = "Checking remote service..."
            _lastError.value = ""
            _remoteResultSummary.value = ""
            val remoteRunStartedAt = System.currentTimeMillis()

            try {
                appendLog("Remote health check requested for $baseUrl")
                val healthStartedAt = System.currentTimeMillis()
                val health = remoteClient.health(baseUrl)
                val healthMs = System.currentTimeMillis() - healthStartedAt
                appendLog("Remote health check result: $health (${formatDurationMs(healthMs)})")

                val request = RemoteGenerateRequest(
                    model = _modelPath.value,
                    userPrompt = prompt
                )
                _statusMessage.value = "Running remote inference..."
                appendLog("Remote generation requested. Prompt length: ${prompt.length}")

                val generateStartedAt = System.currentTimeMillis()
                val response = remoteClient.generate(baseUrl, request)
                val generateMs = System.currentTimeMillis() - generateStartedAt
                val remoteRunMs = System.currentTimeMillis() - remoteRunStartedAt
                _output.value = response.outputText.ifBlank { response.error }
                _remoteBackendLabel.value = response.backendLabel
                _remoteResultSummary.value = buildString {
                    appendLine("RequestId: ${response.requestId}")
                    appendLine("Finish reason: ${response.finishReason}")
                    appendLine("Backend: ${response.backendLabel}")
                    if (response.generationMs >= 0) {
                        appendLine("Generation ms: ${response.generationMs}")
                    }
                    appendLine("Client health check ms: $healthMs")
                    appendLine("Client generation roundtrip ms: $generateMs")
                    appendLine("Client total run ms: $remoteRunMs")
                    appendLine("Output length: ${response.outputText.length}")
                }.trim()
                _statusMessage.value = "Remote inference complete."
                _lastError.value = response.error
                appendLog(
                    "Remote generation completed in ${formatDurationMs(generateMs)}. RequestId=${response.requestId}, finishReason=${response.finishReason}, outputLength=${response.outputText.length}, total=${formatDurationMs(remoteRunMs)}"
                )
            } catch (e: Exception) {
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Remote run error: ${e.message}"
                appendLog("Remote run error: ${e.message ?: "unknown error"}")
            } finally {
                _isGenerating.value = false
                persistDiagnosticSnapshot()
            }
        }
    }

    private fun runSpeculative(prompt: String) {
        viewModelScope.launch {
            if (_isLoadingModel.value || _isGenerating.value) {
                return@launch
            }

            if (prompt.isBlank()) {
                _statusMessage.value = "Please enter a prompt."
                appendLog("Speculative run blocked: prompt is empty.")
                return@launch
            }

            val baseUrl = _remoteServerUrl.value.trim()
            if (baseUrl.isBlank()) {
                _statusMessage.value = "Enter a remote service URL."
                _lastError.value = "Remote service URL is empty."
                appendLog("Speculative run blocked: remote service URL is empty.")
                return@launch
            }

            _isGenerating.value = true
            _statusMessage.value = "Starting speculative session..."
            _lastError.value = ""
            _remoteResultSummary.value = ""
            _speculativeSessionSummary.value = ""
            val speculativeRunStartedAt = System.currentTimeMillis()

            var activeSessionId: String? = null
            var activeLocalDraftSessionId: String? = null
            try {
                appendLog("Speculative health check requested for $baseUrl")
                val healthStartedAt = System.currentTimeMillis()
                val health = remoteClient.health(baseUrl)
                val healthMs = System.currentTimeMillis() - healthStartedAt
                appendLog("Speculative health check result: $health (${formatDurationMs(healthMs)})")

                val startRequest = SpeculativeStartRequest(
                    sessionId = UUID.randomUUID().toString(),
                    draftModel = "android-draft-stub",
                    targetModel = _modelPath.value.ifBlank { "desktop-target" },
                    userPrompt = prompt
                )
                _statusMessage.value = "Opening speculative session..."
                appendLog("Speculative start requested. Prompt length: ${prompt.length}")

                val startStartedAt = System.currentTimeMillis()
                val startResponse = remoteClient.startSpeculativeSession(baseUrl, startRequest)
                val startMs = System.currentTimeMillis() - startStartedAt
                activeSessionId = startResponse.sessionId
                _speculativeVerifierMode.value = startResponse.verifierMode
                appendLog(
                    "Speculative session started in ${formatDurationMs(startMs)}. sessionId=${startResponse.sessionId}, requestId=${startResponse.requestId}, status=${startResponse.status}, verifierMode=${startResponse.verifierMode}"
                )

                val localDraftSupported = runCatching { localLlm.supportsDraftSession() }.getOrDefault(false)
                val localDraftTreeSupported = runCatching { localLlm.supportsDraftTree() }.getOrDefault(false)
                val localDraftReady = runCatching { localLlm.isModelLoaded() }.getOrDefault(false)
                var localDraftOpenMs = -1L
                if (localDraftSupported && localDraftReady) {
                    runCatching {
                        appendLog("Opening local draft session for speculative run.")
                        val openStartedAt = System.currentTimeMillis()
                        localLlm.startDraftSession(
                            systemPrompt = "",
                            userPrompt = prompt,
                            predictLength = LocalLlm.TEST_MAX_TOKENS
                        ).also {
                            localDraftOpenMs = System.currentTimeMillis() - openStartedAt
                        }
                    }.onSuccess { localDraftSession ->
                        activeLocalDraftSessionId = localDraftSession.sessionId
                        appendLog(
                            "Local draft session started in ${formatDurationMs(localDraftOpenMs)}. sessionId=${localDraftSession.sessionId}, acceptedTokenCount=${localDraftSession.acceptedTokenCount}"
                        )
                    }.onFailure { draftError ->
                        appendLog(
                            "Local draft session unavailable; speculative run will fall back to stub draft tokens. ${draftError.message ?: "unknown error"}"
                        )
                    }
                } else if (localDraftSupported) {
                    appendLog("Local draft session supported but local model is not ready; speculative run will use stub draft tokens.")
                } else {
                    appendLog("Local draft session unsupported; speculative run will use stub draft tokens.")
                }

                val draftSeedText = selectSpeculativeStubSeedText(
                    prompt = prompt,
                    verifierMode = startResponse.verifierMode,
                    targetPreviewText = startResponse.targetPreviewText
                )
                val verifierNeedsRealTokenDraft = (
                    startResponse.verifierMode == "llama_true_tree_pq_tokens" ||
                        startResponse.verifierMode == "llama_eagle_aligned" ||
                        startResponse.verifierMode == "llama_cpp_spec_native" ||
                        startResponse.verifierMode == "llama_cpp_spec_split"
                )
                val useReferenceStyleSplitDraft = (
                    startResponse.verifierMode == "llama_cpp_spec_native" ||
                        startResponse.verifierMode == "llama_cpp_spec_split"
                )
                val verifierNeedsDraftTree = (
                    startResponse.verifierMode == "llama_true_tree" ||
                        startResponse.verifierMode == "llama_true_tree_pq_tokens" ||
                        startResponse.verifierMode == "llama_eagle_aligned"
                )
                val useRealTokenDraftPath = verifierNeedsRealTokenDraft && activeLocalDraftSessionId != null
                if (verifierNeedsRealTokenDraft && !useRealTokenDraftPath) {
                    throw IllegalStateException("Verifier mode ${startResponse.verifierMode} requires an active local real-token draft session.")
                }
                val draftSeedTokens = buildStubDraftTokensFromText(draftSeedText)
                val stepTraces = mutableListOf<SpeculativeStepTrace>()
                val committedTokenIds = mutableListOf<Int>()
                var lastWarning = ""
                var lastRequestId = startResponse.requestId
                var lastFinishReason = ""
                var totalDraftFetchMs = 0L
                var totalRemoteProposeMs = 0L
                var totalLocalApplyMs = 0L

                for (draftStep in 1..SPECULATIVE_TEST_MAX_STEPS) {
                    var localDraftTreeProposal: DraftTreeProposal? = null
                    val draftFetchStartedAt = System.currentTimeMillis()
                    val baseTokens = if (activeLocalDraftSessionId != null) {
                        runCatching {
                            if (verifierNeedsDraftTree && localDraftTreeSupported) {
                                val selectedTreeProposal = if (useRealTokenDraftPath) {
                                    localLlm.draftRealTokenTreeProposal(
                                        sessionId = activeLocalDraftSessionId,
                                        maxDepth = SPECULATIVE_TEST_MAX_DRAFT_TOKENS,
                                        branchFactor = 3
                                    )
                                } else {
                                    localLlm.draftTreeProposal(
                                        sessionId = activeLocalDraftSessionId,
                                        maxDepth = SPECULATIVE_TEST_MAX_DRAFT_TOKENS,
                                        branchFactor = 3
                                    )
                                }
                                localDraftTreeProposal = selectedTreeProposal
                                appendLog(
                                    "Local draft tree proposal ready. tokenMode=${selectedTreeProposal.tokenMode}, depth=${selectedTreeProposal.depthEvaluated}, branchFactor=${selectedTreeProposal.branchFactor}, nodeCount=${selectedTreeProposal.nodeCount}, bestPath=${selectedTreeProposal.bestPathTokenIds.joinToString()}, bestPathNodes=${selectedTreeProposal.bestPathNodeIndices.joinToString()}, draftPathSteps=${selectedTreeProposal.draftPathSteps.size}"
                                )
                                selectedTreeProposal.bestPathTokenIds.take(SPECULATIVE_TEST_MAX_DRAFT_TOKENS)
                            } else {
                                if (useRealTokenDraftPath) {
                                    if (useReferenceStyleSplitDraft) {
                                        localLlm.draftNextRealTokenIds(
                                            sessionId = activeLocalDraftSessionId,
                                            maxTokens = SPECULATIVE_TEST_MAX_DRAFT_TOKENS
                                        )
                                    } else {
                                        localLlm.draftNextRealTokenIds(
                                            sessionId = activeLocalDraftSessionId,
                                            maxTokens = SPECULATIVE_TEST_MAX_DRAFT_TOKENS
                                        )
                                    }
                                } else {
                                    localLlm.draftNextTokenIds(
                                        sessionId = activeLocalDraftSessionId,
                                        maxTokens = SPECULATIVE_TEST_MAX_DRAFT_TOKENS
                                    )
                                }
                            }
                        }.onFailure { draftError ->
                            appendLog("Local draft session fetch failed: ${draftError.message ?: "unknown error"}")
                        }.getOrElse { emptyList() }
                    } else {
                        buildStubProposalSlice(
                            seedTokens = draftSeedTokens,
                            committedCount = committedTokenIds.size
                        )
                    }
                    val draftFetchMs = System.currentTimeMillis() - draftFetchStartedAt
                    totalDraftFetchMs += draftFetchMs
                    if (baseTokens.isEmpty()) {
                        appendLog("Speculative loop stopped: no more draft tokens available for step $draftStep.")
                        break
                    }
                    if (baseTokens.size < SPECULATIVE_TEST_MIN_DRAFT_TOKENS) {
                        appendLog(
                            "Speculative loop stopped: draft slice size ${baseTokens.size} is below the benchmark minimum $SPECULATIVE_TEST_MIN_DRAFT_TOKENS for step $draftStep."
                        )
                        break
                    }

                    val proposedTokens = if (activeLocalDraftSessionId == null) {
                        maybeMutateStubDraftTokens(
                            tokenIds = baseTokens,
                            draftStep = draftStep
                        )
                    } else {
                        baseTokens
                    }
                    val draftText = if (useRealTokenDraftPath) {
                        ""
                    } else {
                        tokenIdsToReadableText(proposedTokens)
                    }
                    val traceDraftText = if (useRealTokenDraftPath) {
                        "[render skipped for real-token speculative fast path]"
                    } else {
                        draftText
                    }
                    _statusMessage.value = "Sending speculative draft step $draftStep..."
                    val proposeStartedAt = System.currentTimeMillis()
                    val proposeResponse = remoteClient.proposeDraft(
                        baseUrl = baseUrl,
                        request = SpeculativeProposeRequest(
                            sessionId = startResponse.sessionId,
                            draftStep = draftStep,
                            proposedTokenIds = proposedTokens,
                            proposedText = if (
                                startResponse.verifierMode == "llama_cpp_spec_native" ||
                                startResponse.verifierMode == "llama_cpp_spec_split"
                            ) "" else draftText,
                            maxCorrectionTokens = 1,
                            draftTree = if (
                                startResponse.verifierMode == "llama_cpp_spec_native" ||
                                startResponse.verifierMode == "llama_cpp_spec_split"
                            ) null else localDraftTreeProposal
                        )
                    )
                    val remoteProposeMs = System.currentTimeMillis() - proposeStartedAt
                    totalRemoteProposeMs += remoteProposeMs
                    appendLog(
                        "Speculative propose completed in ${formatDurationMs(remoteProposeMs)}. sessionId=${proposeResponse.sessionId}, draftStep=$draftStep, acceptedCount=${proposeResponse.acceptedCount}, correctionCount=${proposeResponse.correctionTokenIds.size}, status=${proposeResponse.status}, draftFetch=${formatDurationMs(draftFetchMs)}"
                    )

                    committedTokenIds += proposeResponse.acceptedTokenIds
                    committedTokenIds += proposeResponse.correctionTokenIds
                    var localApplyMs = 0L
                    if (activeLocalDraftSessionId != null) {
                        runCatching {
                            val applyStartedAt = System.currentTimeMillis()
                            if (useReferenceStyleSplitDraft) {
                                localLlm.applyVerifiedRealTokens(
                                    sessionId = activeLocalDraftSessionId,
                                    tokenIds = proposeResponse.acceptedTokenIds + proposeResponse.correctionTokenIds
                                )
                            } else if (useRealTokenDraftPath) {
                                localLlm.syncRealTokenDraftSession(
                                    sessionId = activeLocalDraftSessionId,
                                    authoritativeTokenIds = committedTokenIds
                                )
                            } else {
                                val verifiedTokens = proposeResponse.acceptedTokenIds + proposeResponse.correctionTokenIds
                                localLlm.applyVerifiedTokens(
                                    sessionId = activeLocalDraftSessionId,
                                    tokenIds = verifiedTokens
                                )
                            }.also {
                                localApplyMs = System.currentTimeMillis() - applyStartedAt
                            }
                        }.onSuccess { handle ->
                            totalLocalApplyMs += localApplyMs
                            appendLog(
                                "Local draft session advanced in ${formatDurationMs(localApplyMs)}. sessionId=${handle.sessionId}, acceptedTokenCount=${handle.acceptedTokenCount}"
                            )
                        }.onFailure { applyError ->
                            appendLog("Local draft apply failed: ${applyError.message ?: "unknown error"}")
                        }
                    }
                    lastWarning = proposeResponse.warning
                    lastRequestId = proposeResponse.requestId
                    lastFinishReason = proposeResponse.finishReason
                    stepTraces += SpeculativeStepTrace(
                        draftStep = draftStep,
                        proposedTokenIds = proposedTokens,
                        proposedText = traceDraftText,
                        draftFetchMs = draftFetchMs,
                        remoteProposeMs = remoteProposeMs,
                        localApplyMs = localApplyMs,
                        tokenMode = proposeResponse.tokenMode,
                        acceptanceMode = proposeResponse.acceptanceMode,
                        acceptedCount = proposeResponse.acceptedCount,
                        acceptedTokenIds = proposeResponse.acceptedTokenIds,
                        rejectedFromIndex = proposeResponse.rejectedFromIndex,
                        correctionTokenIds = proposeResponse.correctionTokenIds,
                        targetTextDelta = proposeResponse.targetTextDelta,
                        acceptedText = proposeResponse.acceptedText,
                        lastReplayPrompt = proposeResponse.lastReplayPrompt,
                        verifierStage = proposeResponse.verifierStage,
                        trueRuntimeBackend = proposeResponse.trueRuntimeBackend,
                        llamaServerSlotId = proposeResponse.llamaServerSlotId,
                        lastTrueChunkStart = proposeResponse.lastTrueChunkStart,
                        lastTrueChunkConsumed = proposeResponse.lastTrueChunkConsumed,
                        trueCacheHitStreak = proposeResponse.trueCacheHitStreak,
                        trueFetchStreak = proposeResponse.trueFetchStreak,
                        treeCandidateCount = proposeResponse.treeCandidateCount,
                        treeBestPathTokenIds = proposeResponse.treeBestPathTokenIds,
                        treeBranchFactor = proposeResponse.treeBranchFactor,
                        treeDepthEvaluated = proposeResponse.treeDepthEvaluated,
                        treeDebugSummary = proposeResponse.treeDebugSummary,
                        timingPrepareMs = proposeResponse.timingPrepareMs,
                        timingDecodeMs = proposeResponse.timingDecodeMs,
                        timingSampleMs = proposeResponse.timingSampleMs,
                        timingRollbackMs = proposeResponse.timingRollbackMs,
                        timingHelperTotalMs = proposeResponse.timingHelperTotalMs,
                        timingHelperRoundTripMs = proposeResponse.timingHelperRoundTripMs,
                        timingServiceTotalMs = proposeResponse.timingServiceTotalMs,
                        draftTreeNodeCount = proposeResponse.draftTreeNodeCount,
                        draftTreeDepthEvaluated = proposeResponse.draftTreeDepthEvaluated,
                        draftTreeBestPathNodeIndices = proposeResponse.draftTreeBestPathNodeIndices,
                        status = proposeResponse.status,
                        finishReason = proposeResponse.finishReason
                    )

                    if (proposeResponse.finishReason.isNotBlank()) {
                        appendLog("Speculative stub loop stopped at step $draftStep due to finishReason=${proposeResponse.finishReason}")
                        break
                    }
                }

                _statusMessage.value = "Closing speculative session..."
                val closeStartedAt = System.currentTimeMillis()
                val closeResponse = remoteClient.closeSpeculativeSession(
                    baseUrl = baseUrl,
                    request = SpeculativeCloseRequest(
                        sessionId = startResponse.sessionId,
                        reason = "multi_step_stub_completed"
                    )
                )
                val closeMs = System.currentTimeMillis() - closeStartedAt
                val speculativeRunMs = System.currentTimeMillis() - speculativeRunStartedAt
                appendLog(
                    "Speculative session closed in ${formatDurationMs(closeMs)}. sessionId=${closeResponse.sessionId}, acceptedTokenCount=${closeResponse.acceptedTokenCount}, mismatchCount=${closeResponse.mismatchCount}, total=${formatDurationMs(speculativeRunMs)}"
                )
                activeSessionId = null

                val finalStep = stepTraces.lastOrNull()
                val totalCommittedTokens = committedTokenIds.size
                val averageDraftFetchMs = if (stepTraces.isNotEmpty()) totalDraftFetchMs.toDouble() / stepTraces.size else 0.0
                val averageRemoteProposeMs = if (stepTraces.isNotEmpty()) totalRemoteProposeMs.toDouble() / stepTraces.size else 0.0
                val averageLocalApplyMs = if (stepTraces.isNotEmpty()) totalLocalApplyMs.toDouble() / stepTraces.size else 0.0
                val averageVerifyPrepareMs = if (stepTraces.isNotEmpty()) stepTraces.map { it.timingPrepareMs }.average() else 0.0
                val averageVerifyDecodeMs = if (stepTraces.isNotEmpty()) stepTraces.map { it.timingDecodeMs }.average() else 0.0
                val averageVerifySampleMs = if (stepTraces.isNotEmpty()) stepTraces.map { it.timingSampleMs }.average() else 0.0
                val averageVerifyRollbackMs = if (stepTraces.isNotEmpty()) stepTraces.map { it.timingRollbackMs }.average() else 0.0
                val averageHelperRoundTripMs = if (stepTraces.isNotEmpty()) stepTraces.map { it.timingHelperRoundTripMs }.average() else 0.0
                val averageServiceTotalMs = if (stepTraces.isNotEmpty()) stepTraces.map { it.timingServiceTotalMs }.average() else 0.0
                val averageEstimatedTransportMs = if (stepTraces.isNotEmpty()) stepTraces.map {
                    (it.remoteProposeMs.toDouble() - it.timingServiceTotalMs).coerceAtLeast(0.0)
                }.average() else 0.0
                val overallTokensPerSecond = if (speculativeRunMs > 0) totalCommittedTokens * 1000.0 / speculativeRunMs else 0.0
                val draftTokensPerSecond = if (totalDraftFetchMs > 0) stepTraces.sumOf { it.proposedTokenIds.size } * 1000.0 / totalDraftFetchMs else 0.0

                _speculativeSessionSummary.value = buildString {
                    appendLine("SessionId: ${startResponse.sessionId}")
                    appendLine("Start status: ${startResponse.status}")
                    appendLine("Target session id: ${startResponse.targetSessionId}")
                    appendLine("Verifier mode: ${startResponse.verifierMode}")
                    appendLine("Verifier stage: ${startResponse.verifierStage}")
                    if (startResponse.trueRuntimeBackend.isNotBlank()) {
                        appendLine("True runtime backend: ${startResponse.trueRuntimeBackend}")
                    }
                    if (startResponse.llamaServerSlotId >= 0) {
                        appendLine("Llama server slot id: ${startResponse.llamaServerSlotId}")
                    }
                    appendLine("Target preview text: ${startResponse.targetPreviewText}")
                    appendLine("Start accepted text: ${startResponse.acceptedText}")
                    if (startResponse.lastReplayPrompt.isNotBlank()) {
                        appendLine("Start replay prompt: ${startResponse.lastReplayPrompt}")
                    }
                    appendLine("Draft seed text: $draftSeedText")
                    appendLine("Draft token mode: ${if (useRealTokenDraftPath) "real_token" else "codepoint_legacy"}")
                    appendLine("Local draft session supported: $localDraftSupported")
                    appendLine("Local draft session active: ${activeLocalDraftSessionId ?: ""}")
                    appendLine("Timing total ms: $speculativeRunMs")
                    appendLine("Timing health check ms: $healthMs")
                    appendLine("Timing start session ms: $startMs")
                    appendLine("Timing local draft open ms: ${if (localDraftOpenMs >= 0) localDraftOpenMs else -1}")
                    appendLine("Timing total draft fetch ms: $totalDraftFetchMs")
                    appendLine("Timing total remote propose ms: $totalRemoteProposeMs")
                    appendLine("Timing total local apply ms: $totalLocalApplyMs")
                    appendLine("Timing close session ms: $closeMs")
                    appendLine("Timing avg draft fetch ms: ${"%.3f".format(averageDraftFetchMs)}")
                    appendLine("Timing avg remote propose ms: ${"%.3f".format(averageRemoteProposeMs)}")
                    appendLine("Timing avg local apply ms: ${"%.3f".format(averageLocalApplyMs)}")
                    appendLine("Timing avg verify prepare ms: ${"%.3f".format(averageVerifyPrepareMs)}")
                    appendLine("Timing avg verify decode ms: ${"%.3f".format(averageVerifyDecodeMs)}")
                    appendLine("Timing avg verify sample ms: ${"%.3f".format(averageVerifySampleMs)}")
                    appendLine("Timing avg verify rollback ms: ${"%.3f".format(averageVerifyRollbackMs)}")
                    appendLine("Timing avg helper round trip ms: ${"%.3f".format(averageHelperRoundTripMs)}")
                    appendLine("Timing avg service total ms: ${"%.3f".format(averageServiceTotalMs)}")
                    appendLine("Timing avg estimated transport ms: ${"%.3f".format(averageEstimatedTransportMs)}")
                    appendLine("Draft steps completed: ${stepTraces.size}")
                    appendLine("Committed token ids: ${committedTokenIds.joinToString()}")
                    appendLine("Committed token count: $totalCommittedTokens")
                    appendLine("Overall generated t/s: ${"%.3f".format(overallTokensPerSecond)}")
                    appendLine("Draft proposed t/s: ${"%.3f".format(draftTokensPerSecond)}")
                    appendLine(
                        "Committed text: ${
                            if (useRealTokenDraftPath) runCatching { localLlm.renderTokenIds(committedTokenIds) }.getOrElse { tokenIdsToReadableText(committedTokenIds) }
                            else tokenIdsToReadableText(committedTokenIds)
                        }"
                    )
                    if (finalStep != null) {
                        appendLine("Final step status: ${finalStep.status}")
                        if (finalStep.tokenMode.isNotBlank()) {
                            appendLine("Final token mode: ${finalStep.tokenMode}")
                        }
                        if (finalStep.acceptanceMode.isNotBlank()) {
                            appendLine("Final acceptance mode: ${finalStep.acceptanceMode}")
                        }
                        appendLine("Final accepted count: ${finalStep.acceptedCount}")
                        appendLine("Final rejected from index: ${finalStep.rejectedFromIndex}")
                        appendLine("Final correction token ids: ${finalStep.correctionTokenIds.joinToString()}")
                        appendLine("Final target text delta: ${finalStep.targetTextDelta}")
                        appendLine("Final accepted text: ${finalStep.acceptedText}")
                        appendLine("Final verifier stage: ${finalStep.verifierStage}")
                        if (finalStep.trueRuntimeBackend.isNotBlank()) {
                            appendLine("Final true runtime backend: ${finalStep.trueRuntimeBackend}")
                        }
                        if (finalStep.llamaServerSlotId >= 0) {
                            appendLine("Final llama server slot id: ${finalStep.llamaServerSlotId}")
                        }
                        if (finalStep.lastTrueChunkStart >= 0) {
                            appendLine("Final true chunk start: ${finalStep.lastTrueChunkStart}")
                            appendLine("Final true chunk consumed: ${finalStep.lastTrueChunkConsumed}")
                            appendLine("Final true cache hit streak: ${finalStep.trueCacheHitStreak}")
                            appendLine("Final true fetch streak: ${finalStep.trueFetchStreak}")
                        }
                        if (finalStep.lastReplayPrompt.isNotBlank()) {
                            appendLine("Final replay prompt: ${finalStep.lastReplayPrompt}")
                        }
                        appendLine("Final verify prepare ms: ${"%.3f".format(finalStep.timingPrepareMs)}")
                        appendLine("Final verify decode ms: ${"%.3f".format(finalStep.timingDecodeMs)}")
                        appendLine("Final verify sample ms: ${"%.3f".format(finalStep.timingSampleMs)}")
                        appendLine("Final verify rollback ms: ${"%.3f".format(finalStep.timingRollbackMs)}")
                        appendLine("Final helper round trip ms: ${"%.3f".format(finalStep.timingHelperRoundTripMs)}")
                        appendLine("Final service total ms: ${"%.3f".format(finalStep.timingServiceTotalMs)}")
                        if (finalStep.treeCandidateCount > 0) {
                            appendLine("Final tree candidate count: ${finalStep.treeCandidateCount}")
                            appendLine("Final tree branch factor: ${finalStep.treeBranchFactor}")
                            appendLine("Final tree depth evaluated: ${finalStep.treeDepthEvaluated}")
                            appendLine("Final tree best path: ${finalStep.treeBestPathTokenIds.joinToString()}")
                            appendLine("Final tree debug: ${finalStep.treeDebugSummary}")
                            appendLine("Final draft tree node count: ${finalStep.draftTreeNodeCount}")
                            appendLine("Final draft tree depth evaluated: ${finalStep.draftTreeDepthEvaluated}")
                            appendLine("Final draft tree best path nodes: ${finalStep.draftTreeBestPathNodeIndices.joinToString()}")
                        }
                    }
                    appendLine("Close status: ${closeResponse.status}")
                    appendLine("Close accepted text: ${closeResponse.acceptedText}")
                    appendLine("Close last target text delta: ${closeResponse.lastTargetTextDelta}")
                    if (closeResponse.trueRuntimeBackend.isNotBlank()) {
                        appendLine("Close true runtime backend: ${closeResponse.trueRuntimeBackend}")
                    }
                    if (closeResponse.llamaServerSlotId >= 0) {
                        appendLine("Close llama server slot id: ${closeResponse.llamaServerSlotId}")
                    }
                    appendLine("Fallback available: ${startResponse.fallbackAvailable}")
                    appendLine("Force mismatch: ${_speculativeForceMismatch.value}")
                    if (stepTraces.isNotEmpty()) {
                        appendLine("Step trace:")
                        stepTraces.forEach { trace ->
                            appendLine(
                                "  Step ${trace.draftStep}: proposed=${trace.proposedTokenIds.joinToString()} accepted=${trace.acceptedTokenIds.joinToString()} correction=${trace.correctionTokenIds.joinToString()} status=${trace.status}"
                            )
                        }
                    }
                    if (lastWarning.isNotBlank()) {
                        appendLine("Warning: $lastWarning")
                    }
                }.trim()
                _remoteResultSummary.value = buildString {
                    appendLine("Speculative stub requestId: $lastRequestId")
                    appendLine("Verifier mode: ${startResponse.verifierMode}")
                    appendLine("Verifier stage: ${finalStep?.verifierStage ?: startResponse.verifierStage}")
                    if ((finalStep?.trueRuntimeBackend ?: startResponse.trueRuntimeBackend).isNotBlank()) {
                        appendLine("True runtime backend: ${finalStep?.trueRuntimeBackend ?: startResponse.trueRuntimeBackend}")
                    }
                    val activeSlotId = finalStep?.llamaServerSlotId ?: startResponse.llamaServerSlotId
                    if (activeSlotId >= 0) {
                        appendLine("Llama server slot id: $activeSlotId")
                    }
                    appendLine("Steps completed: ${stepTraces.size}")
                    appendLine("Final verify status: ${finalStep?.status ?: "not_run"}")
                    if (!finalStep?.tokenMode.isNullOrBlank()) {
                        appendLine("Token mode: ${finalStep?.tokenMode}")
                    }
                    if (!finalStep?.acceptanceMode.isNullOrBlank()) {
                        appendLine("Acceptance mode: ${finalStep?.acceptanceMode}")
                    }
                    appendLine("Final accepted count: ${finalStep?.acceptedCount ?: 0}")
                    appendLine("Final rejected from index: ${finalStep?.rejectedFromIndex ?: -1}")
                    appendLine("Final correction count: ${finalStep?.correctionTokenIds?.size ?: 0}")
                    appendLine("Tree candidate count: ${finalStep?.treeCandidateCount ?: 0}")
                    appendLine("Tree depth evaluated: ${finalStep?.treeDepthEvaluated ?: 0}")
                    appendLine("Draft tree node count: ${finalStep?.draftTreeNodeCount ?: 0}")
                    appendLine("Committed token count: ${committedTokenIds.size}")
                    appendLine("Local draft session supported: $localDraftSupported")
                    appendLine("Timing total ms: $speculativeRunMs")
                    appendLine("Timing health check ms: $healthMs")
                    appendLine("Timing start session ms: $startMs")
                    appendLine("Timing local draft open ms: ${if (localDraftOpenMs >= 0) localDraftOpenMs else -1}")
                    appendLine("Timing total draft fetch ms: $totalDraftFetchMs")
                    appendLine("Timing total remote propose ms: $totalRemoteProposeMs")
                    appendLine("Timing total local apply ms: $totalLocalApplyMs")
                    appendLine("Timing close session ms: $closeMs")
                    appendLine("Close accepted text: ${closeResponse.acceptedText}")
                    appendLine("Finish reason: ${lastFinishReason.ifBlank { "stub" }}")
                    appendLine("Close reason: ${closeResponse.reason}")
                }.trim()
                val finalCommittedText = when {
                    closeResponse.acceptedText.isNotBlank() -> closeResponse.acceptedText
                    committedTokenIds.isEmpty() -> ""
                    useRealTokenDraftPath -> runCatching {
                        localLlm.renderTokenIds(committedTokenIds)
                    }.getOrElse {
                        tokenIdsToReadableText(committedTokenIds)
                    }
                    else -> tokenIdsToReadableText(committedTokenIds)
                }
                _output.value = if (lastWarning.isNotBlank()) {
                    buildString {
                        appendLine(finalCommittedText)
                        appendLine()
                        appendLine(lastWarning)
                    }.trim()
                } else {
                    finalCommittedText
                }
                _statusMessage.value = "Speculative multi-step stub complete."
                _lastError.value = listOf(
                    startResponse.error,
                    closeResponse.error
                ).firstOrNull { it.isNotBlank() }.orEmpty()
            } catch (e: Exception) {
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Speculative run error: ${e.message}"
                appendLog("Speculative run error: ${e.message ?: "unknown error"}")
                if (activeSessionId != null) {
                    val sessionIdToClose = activeSessionId
                    runCatching {
                        remoteClient.closeSpeculativeSession(
                            baseUrl = baseUrl,
                            request = SpeculativeCloseRequest(
                                sessionId = sessionIdToClose,
                                reason = "error_cleanup"
                            )
                        )
                    }.onSuccess { response ->
                        appendLog("Speculative cleanup close succeeded. sessionId=${response.sessionId}")
                    }.onFailure { closeError ->
                        appendLog("Speculative cleanup close failed: ${closeError.message ?: "unknown error"}")
                    }
                }
                if (activeLocalDraftSessionId != null) {
                    val localSessionIdToClose = activeLocalDraftSessionId
                    runCatching {
                        localLlm.closeDraftSession(localSessionIdToClose)
                    }.onSuccess {
                        appendLog("Local draft session cleanup close succeeded. sessionId=$localSessionIdToClose")
                    }.onFailure { closeError ->
                        appendLog("Local draft session cleanup close failed: ${closeError.message ?: "unknown error"}")
                    }
                }
            } finally {
                if (activeLocalDraftSessionId != null) {
                    val localSessionIdToClose = activeLocalDraftSessionId
                    runCatching { localLlm.closeDraftSession(localSessionIdToClose) }
                }
                _isGenerating.value = false
                persistDiagnosticSnapshot()
            }
        }
    }

    private fun refreshNativeState() {
        _isModelLoaded.value = runCatching { localLlm.isModelLoaded() }.getOrDefault(false)
        _loadedModelPath.value = runCatching { localLlm.loadedModelPath() }.getOrDefault("")
        _lastError.value = runCatching { localLlm.lastError() }.getOrDefault("")
        persistDiagnosticSnapshot()
    }

    private fun formatDurationMs(durationMs: Long): String {
        return "${durationMs} ms"
    }

    private fun appendLog(message: String) {
        val timestamp = System.currentTimeMillis()
        _eventLog.value = buildString {
            append(_eventLog.value)
            appendLine()
            append("[$timestamp] ")
            append(message)
        }
        persistDiagnosticSnapshot()
    }

    private fun persistDiagnosticSnapshot() {
        val application = getApplication<Application>()
        val logFile = diagnosticLogFile()
        logFile.parentFile?.mkdirs()
        val snapshot = buildString {
            appendLine("Inference mode: ${_inferenceMode.value.name}")
            appendLine("Backend: ${_backendLabel.value}")
            appendLine("Remote server URL: ${_remoteServerUrl.value}")
            appendLine("Remote backend: ${_remoteBackendLabel.value}")
            appendLine("Remote probe summary: ${_remoteProbeSummary.value}")
            appendLine("Remote result summary: ${_remoteResultSummary.value}")
            appendLine("Speculative session summary: ${_speculativeSessionSummary.value}")
            appendLine("Speculative force mismatch: ${_speculativeForceMismatch.value}")
            appendLine("Speculative verifier mode: ${_speculativeVerifierMode.value}")
            appendLine("Local draft session supported: ${runCatching { localLlm.supportsDraftSession() }.getOrDefault(false)}")
            appendLine("Status: ${_statusMessage.value}")
            appendLine("Model loaded: ${_isModelLoaded.value}")
            appendLine("Selected model: ${_modelPath.value}")
            appendLine("Loaded model path: ${_loadedModelPath.value}")
            appendLine("Last error: ${_lastError.value}")
            appendLine("Diagnostic log path: ${logFile.absolutePath}")
            appendLine()
            appendLine("Event Log:")
            appendLine(_eventLog.value)
            appendLine()
            appendLine("Output:")
            appendLine(_output.value)
        }
        runCatching {
            logFile.writeText(snapshot)
            _diagnosticLogPath.value = logFile.absolutePath
        }.onFailure {
            android.util.Log.e("MainViewModel", "Failed to write diagnostic log", it)
        }
    }

    private fun diagnosticLogFile(): File {
        val application = getApplication<Application>()
        return File(application.filesDir, "logs/diagnostic-latest.txt")
    }

    private fun buildStubDraftTokens(prompt: String): List<Int> {
        val trimmed = prompt.trim()
        if (trimmed.isBlank()) {
            return listOf(0)
        }

        val tokens = trimmed
            .codePoints()
            .limit(4)
            .toArray()
            .map { it.toInt() }
            .filter { it > 0 }

        return if (tokens.isEmpty()) listOf(trimmed.length) else tokens
    }

    private fun buildStubDraftTokensFromText(text: String): List<Int> {
        val normalized = text.trim()
        if (normalized.isBlank()) {
            return listOf(0)
        }

        return normalized
            .codePoints()
            .limit(96)
            .toArray()
            .map { it.toInt() }
            .filter { it > 0 }
            .ifEmpty { listOf(normalized.length) }
    }

    private fun buildStubProposalSlice(seedTokens: List<Int>, committedCount: Int): List<Int> {
        if (seedTokens.isEmpty()) {
            return emptyList()
        }
        if (committedCount >= seedTokens.size) {
            return emptyList()
        }
        return seedTokens.drop(committedCount).take(SPECULATIVE_TEST_MAX_DRAFT_TOKENS)
    }

    private fun selectSpeculativeStubSeedText(
        prompt: String,
        verifierMode: String,
        targetPreviewText: String
    ): String {
        return if (verifierMode.startsWith("llama_") && targetPreviewText.isNotBlank()) {
            targetPreviewText
        } else {
            prompt.trim()
        }
    }

    private fun maybeMutateStubDraftTokens(tokenIds: List<Int>, draftStep: Int): List<Int> {
        if (!_speculativeForceMismatch.value || tokenIds.isEmpty()) {
            return tokenIds
        }

        return tokenIds.mapIndexed { index, tokenId ->
            if (draftStep == 1 && (index == 1 || (index == 0 && tokenIds.size == 1))) {
                tokenId + 1
            } else {
                tokenId
            }
        }
    }

    private fun tokenIdsToReadableText(tokenIds: List<Int>): String {
        if (tokenIds.isEmpty()) {
            return ""
        }
        return buildString {
            tokenIds.forEach { tokenId ->
                if (tokenId in 32..126) {
                    append(tokenId.toChar())
                } else {
                    append("<")
                    append(tokenId)
                    append(">")
                }
            }
        }
    }

    override fun onCleared() {
        runCatching { localLlm.cleanup() }
        super.onCleared()
    }

    private fun findModelFilesInDirectory(directoryUri: Uri): List<ModelCandidate> {
        val application = getApplication<Application>()
        val tree = DocumentFile.fromTreeUri(application, directoryUri) ?: return emptyList()

        return tree.listFiles()
            .filter { it.isFile && it.name?.endsWith(".gguf", ignoreCase = true) == true }
            .sortedBy { it.name.orEmpty() }
            .mapNotNull { file ->
                val name = file.name ?: return@mapNotNull null
                ModelCandidate(
                    name = name,
                    contentUri = file.uri.toString(),
                    sizeBytes = file.length()
                )
            }
    }

    private fun ensureReadableLocalModelCopy(candidate: ModelCandidate): File {
        val application = getApplication<Application>()
        val sourceUri = Uri.parse(candidate.contentUri)
        val targetDir = File(application.filesDir, "imported-models").apply {
            mkdirs()
        }
        val targetFile = File(targetDir, candidate.name)

        if (targetFile.exists() && targetFile.length() > 0L && targetFile.length() == candidate.sizeBytes) {
            return targetFile
        }

        application.contentResolver.openInputStream(sourceUri).use { input ->
            requireNotNull(input) { "Cannot open selected model file." }
            targetFile.outputStream().use { output ->
                input.copyTo(output)
            }
        }

        require(targetFile.exists() && targetFile.canRead()) {
            "Imported model copy is not readable."
        }
        if (candidate.sizeBytes > 0L) {
            require(targetFile.length() == candidate.sizeBytes) {
                "Imported model copy size mismatch: expected ${candidate.sizeBytes} bytes, got ${targetFile.length()} bytes."
            }
        }
        require(readGgufHeader(targetFile) == "GGUF") {
            "Imported model copy does not start with a GGUF header."
        }
        return targetFile
    }

    private fun readGgufHeader(file: File): String {
        RandomAccessFile(file, "r").use { raf ->
            val header = ByteArray(4)
            val bytesRead = raf.read(header)
            require(bytesRead == 4) { "Imported model copy is too short to contain a GGUF header." }
            return String(header, Charsets.US_ASCII)
        }
    }
}
