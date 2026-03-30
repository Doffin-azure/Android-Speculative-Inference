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
            val statusMessage by viewModel.statusMessage.collectAsState()
            val output by viewModel.output.collectAsState()
            val lastError by viewModel.lastError.collectAsState()
            val isModelLoaded by viewModel.isModelLoaded.collectAsState()
            val isLoadingModel by viewModel.isLoadingModel.collectAsState()
            val isGenerating by viewModel.isGenerating.collectAsState()
            val modelPath by viewModel.modelPath.collectAsState()
            val loadedModelPath by viewModel.loadedModelPath.collectAsState()

            MainScreen(
                backendLabel = backendLabel,
                statusMessage = statusMessage,
                output = output,
                lastError = lastError,
                isModelLoaded = isModelLoaded,
                isLoadingModel = isLoadingModel,
                isGenerating = isGenerating,
                modelPath = modelPath,
                loadedModelPath = loadedModelPath,
                onModelPathChange = { viewModel.updateModelPath(it) },
                onPickModelDirectory = {
                    directoryPicker.launch(null)
                },
                onLoadModel = { viewModel.loadModel() },
                onRun = { prompt -> viewModel.runLocal(prompt) }
            )
        }
    }
}
