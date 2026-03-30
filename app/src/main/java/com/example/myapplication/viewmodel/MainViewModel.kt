package com.example.myapplication.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.example.myapplication.inference.LocalLlm
import com.example.myapplication.inference.LocalLlmImpl
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

class MainViewModel(
    private val localLlm: LocalLlm = LocalLlmImpl()
) : ViewModel() {

    private val _backendLabel = MutableStateFlow("Detecting backend...")
    val backendLabel: StateFlow<String> = _backendLabel.asStateFlow()

    private val _output = MutableStateFlow("Ready")
    val output: StateFlow<String> = _output.asStateFlow()

    private val _statusMessage = MutableStateFlow("Idle")
    val statusMessage: StateFlow<String> = _statusMessage.asStateFlow()

    private val _isModelLoaded = MutableStateFlow(false)
    val isModelLoaded: StateFlow<Boolean> = _isModelLoaded.asStateFlow()

    private val _modelPath = MutableStateFlow("")
    val modelPath: StateFlow<String> = _modelPath.asStateFlow()

    private val _loadedModelPath = MutableStateFlow("")
    val loadedModelPath: StateFlow<String> = _loadedModelPath.asStateFlow()

    private val _lastError = MutableStateFlow("")
    val lastError: StateFlow<String> = _lastError.asStateFlow()

    private val _isLoadingModel = MutableStateFlow(false)
    val isLoadingModel: StateFlow<Boolean> = _isLoadingModel.asStateFlow()

    private val _isGenerating = MutableStateFlow(false)
    val isGenerating: StateFlow<Boolean> = _isGenerating.asStateFlow()

    init {
        _backendLabel.value = try {
            localLlm.backendLabel()
        } catch (e: Exception) {
            "Backend unavailable: ${e.message ?: "unknown error"}"
        }

        refreshNativeState()
    }

    fun updateModelPath(path: String) {
        _modelPath.value = path
    }

    fun loadModel() {
        viewModelScope.launch {
            if (_isLoadingModel.value || _isGenerating.value) {
                return@launch
            }

            if (_modelPath.value.isBlank()) {
                _statusMessage.value = "Please enter a model path."
                _lastError.value = "Model path is empty."
                return@launch
            }

            _isLoadingModel.value = true
            _statusMessage.value = "Loading model..."
            _lastError.value = ""
            try {
                val ok = localLlm.loadModel(_modelPath.value)
                refreshNativeState()
                _statusMessage.value = if (ok) {
                    "Model loaded."
                } else {
                    "Model load failed."
                }
            } catch (e: Exception) {
                _isModelLoaded.value = false
                _loadedModelPath.value = ""
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Load error: ${e.message}"
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
                return@launch
            }

            if (prompt.isBlank()) {
                _statusMessage.value = "Please enter a prompt."
                return@launch
            }

            _isGenerating.value = true
            _statusMessage.value = "Running..."
            _lastError.value = ""
            try {
                _output.value = localLlm.generate(prompt)
                refreshNativeState()
                _statusMessage.value = "Inference complete."
            } catch (e: Exception) {
                _lastError.value = e.message ?: "unknown error"
                _statusMessage.value = "Run error: ${e.message}"
            } finally {
                _isGenerating.value = false
            }
        }
    }

    private fun refreshNativeState() {
        _isModelLoaded.value = runCatching { localLlm.isModelLoaded() }.getOrDefault(false)
        _loadedModelPath.value = runCatching { localLlm.loadedModelPath() }.getOrDefault("")
        _lastError.value = runCatching { localLlm.lastError() }.getOrDefault("")
    }
}
