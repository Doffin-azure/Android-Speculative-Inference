package com.example.myapplication.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import com.example.myapplication.viewmodel.MainViewModel
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun MainScreen(
    backendLabel: String,
    statusMessage: String,
    output: String,
    lastError: String,
    isModelLoaded: Boolean,
    isLoadingModel: Boolean,
    isGenerating: Boolean,
    modelPath: String,
    modelCandidates: List<MainViewModel.ModelCandidate>,
    loadedModelPath: String,
    onPickModelDirectory: () -> Unit,
    onSelectModelCandidate: (String) -> Unit,
    onLoadModel: () -> Unit,
    onRun: (String) -> Unit
) {
    var prompt by remember { mutableStateOf("") }
    val busy = isLoadingModel || isGenerating

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
    ) {
        Text(text = "Backend: $backendLabel")

        Text(
            text = if (isModelLoaded) "Model: Loaded" else "Model: Not loaded",
            modifier = Modifier.padding(top = 8.dp)
        )

        Text(
            text = "Status: $statusMessage",
            modifier = Modifier.padding(top = 8.dp)
        )

        if (loadedModelPath.isNotBlank()) {
            Text(
                text = "Loaded path: $loadedModelPath",
                modifier = Modifier.padding(top = 8.dp)
            )
        }

        if (lastError.isNotBlank()) {
            Text(
                text = "Last error: $lastError",
                modifier = Modifier.padding(top = 8.dp)
            )
        }

        TextField(
            value = modelPath,
            onValueChange = {},
            label = { Text("Model File Path") },
            readOnly = true,
            enabled = true,
            modifier = Modifier.padding(top = 16.dp)
        )

        Button(
            onClick = onPickModelDirectory,
            enabled = !busy,
            modifier = Modifier.padding(top = 16.dp)
        ) {
            Text("Pick Model Directory")
        }

        if (modelCandidates.size > 1) {
            Text(
                text = "Models found in directory:",
                modifier = Modifier.padding(top = 16.dp)
            )

            modelCandidates.forEach { candidate ->
                Button(
                    onClick = { onSelectModelCandidate(candidate.path) },
                    enabled = !busy,
                    modifier = Modifier.padding(top = 8.dp)
                ) {
                    Text(candidate.name)
                }
            }
        }

        Button(
            onClick = onLoadModel,
            enabled = !busy && modelPath.isNotBlank(),
            modifier = Modifier.padding(top = 16.dp)
        ) {
            Text(if (isLoadingModel) "Loading..." else "Load Model")
        }

        TextField(
            value = prompt,
            onValueChange = { prompt = it },
            label = { Text("Prompt") },
            enabled = !busy && isModelLoaded,
            modifier = Modifier.padding(top = 16.dp)
        )

        Button(
            onClick = { onRun(prompt) },
            enabled = !busy && isModelLoaded,
            modifier = Modifier.padding(top = 16.dp)
        ) {
            Text(if (isGenerating) "Running..." else "Run Local")
        }

        Text(
            text = output,
            modifier = Modifier.padding(top = 16.dp)
        )
    }
}
