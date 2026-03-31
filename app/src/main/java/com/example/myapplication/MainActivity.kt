package com.example.myapplication

import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import com.example.myapplication.ui.MainScreen
import com.example.myapplication.viewmodel.MainViewModel

class MainActivity : ComponentActivity() {
    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        setContent {
            val directoryPicker = rememberLauncherForActivityResult(
                contract = ActivityResultContracts.OpenDocumentTree()
            ) { uri: Uri? ->
                uri?.let(viewModel::onModelDirectorySelected)
            }

            val backendLabel by viewModel.backendLabel.collectAsState()
            val inferenceMode by viewModel.inferenceMode.collectAsState()
            val remoteServerUrl by viewModel.remoteServerUrl.collectAsState()
            val remoteBackendLabel by viewModel.remoteBackendLabel.collectAsState()
            val remoteProbeSummary by viewModel.remoteProbeSummary.collectAsState()
            val remoteResultSummary by viewModel.remoteResultSummary.collectAsState()
            val statusMessage by viewModel.statusMessage.collectAsState()
            val output by viewModel.output.collectAsState()
            val lastError by viewModel.lastError.collectAsState()
            val eventLog by viewModel.eventLog.collectAsState()
            val diagnosticLogPath by viewModel.diagnosticLogPath.collectAsState()
            val isModelLoaded by viewModel.isModelLoaded.collectAsState()
            val isLoadingModel by viewModel.isLoadingModel.collectAsState()
            val isGenerating by viewModel.isGenerating.collectAsState()
            val modelPath by viewModel.modelPath.collectAsState()
            val modelCandidates by viewModel.modelCandidates.collectAsState()
            val loadedModelPath by viewModel.loadedModelPath.collectAsState()

            MainScreen(
                backendLabel = backendLabel,
                inferenceMode = inferenceMode,
                remoteServerUrl = remoteServerUrl,
                remoteBackendLabel = remoteBackendLabel,
                remoteProbeSummary = remoteProbeSummary,
                remoteResultSummary = remoteResultSummary,
                statusMessage = statusMessage,
                output = output,
                lastError = lastError,
                eventLog = eventLog,
                diagnosticLogPath = diagnosticLogPath,
                isModelLoaded = isModelLoaded,
                isLoadingModel = isLoadingModel,
                isGenerating = isGenerating,
                modelPath = modelPath,
                modelCandidates = modelCandidates,
                loadedModelPath = loadedModelPath,
                onPickModelDirectory = {
                    directoryPicker.launch(null)
                },
                onSetInferenceMode = viewModel::setInferenceMode,
                onRemoteServerUrlChange = viewModel::setRemoteServerUrl,
                onTestRemoteConnectivity = viewModel::testRemoteConnectivity,
                onSelectModelCandidate = viewModel::selectModelCandidate,
                onLoadModel = { viewModel.loadModel() },
                onRun = { prompt -> viewModel.runInference(prompt) }
            )
        }
    }
}
