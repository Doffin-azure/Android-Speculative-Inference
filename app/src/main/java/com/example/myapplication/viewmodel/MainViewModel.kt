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
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File
import java.io.RandomAccessFile

class MainViewModel(
    application: Application
) : AndroidViewModel(application) {

    enum class InferenceMode {
        LOCAL,
        REMOTE
    }

    data class ModelCandidate(
        val name: String,
        val contentUri: String,
        val sizeBytes: Long
    )

    private val localLlm: LocalLlm = LocalLlmImpl(application.applicationContext)
    private val remoteClient = RemoteInferenceClient()

    private val _backendLabel = MutableStateFlow("Detecting backend...")
    val backendLabel: StateFlow<String> = _backendLabel.asStateFlow()

    private val _inferenceMode = MutableStateFlow(InferenceMode.LOCAL)
    val inferenceMode: StateFlow<InferenceMode> = _inferenceMode.asStateFlow()

    private val _remoteServerUrl = MutableStateFlow("http://10.0.2.2:8080")
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
        }
        appendLog("Inference mode changed to ${mode.name}.")
    }

    fun setRemoteServerUrl(url: String) {
        _remoteServerUrl.value = url
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
                _output.value = localLlm.generate(prompt)
                refreshNativeState()
                _statusMessage.value = "Inference complete."
                appendLog("Generation completed. Output length: ${_output.value.length}")
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

            try {
                appendLog("Remote health check requested for $baseUrl")
                val health = remoteClient.health(baseUrl)
                appendLog("Remote health check result: $health")

                val request = RemoteGenerateRequest(
                    model = _modelPath.value,
                    userPrompt = prompt
                )
                _statusMessage.value = "Running remote inference..."
                appendLog("Remote generation requested. Prompt length: ${prompt.length}")

                val response = remoteClient.generate(baseUrl, request)
                _output.value = response.outputText.ifBlank { response.error }
                _remoteBackendLabel.value = response.backendLabel
                _statusMessage.value = "Remote inference complete."
                _lastError.value = response.error
                appendLog(
                    "Remote generation completed. RequestId=${response.requestId}, finishReason=${response.finishReason}, outputLength=${response.outputText.length}"
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

    private fun refreshNativeState() {
        _isModelLoaded.value = runCatching { localLlm.isModelLoaded() }.getOrDefault(false)
        _loadedModelPath.value = runCatching { localLlm.loadedModelPath() }.getOrDefault("")
        _lastError.value = runCatching { localLlm.lastError() }.getOrDefault("")
        persistDiagnosticSnapshot()
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
