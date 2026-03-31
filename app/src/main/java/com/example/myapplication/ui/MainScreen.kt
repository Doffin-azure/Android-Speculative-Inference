package com.example.myapplication.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.runtime.Composable
import com.example.myapplication.viewmodel.MainViewModel
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun MainScreen(
    backendLabel: String,
    inferenceMode: MainViewModel.InferenceMode,
    remoteServerUrl: String,
    remoteBackendLabel: String,
    statusMessage: String,
    output: String,
    lastError: String,
    eventLog: String,
    diagnosticLogPath: String,
    isModelLoaded: Boolean,
    isLoadingModel: Boolean,
    isGenerating: Boolean,
    modelPath: String,
    modelCandidates: List<MainViewModel.ModelCandidate>,
    loadedModelPath: String,
    onPickModelDirectory: () -> Unit,
    onSetInferenceMode: (MainViewModel.InferenceMode) -> Unit,
    onRemoteServerUrlChange: (String) -> Unit,
    onSelectModelCandidate: (String) -> Unit,
    onLoadModel: () -> Unit,
    onRun: (String) -> Unit
) {
    var prompt by remember { mutableStateOf("") }
    val busy = isLoadingModel || isGenerating
    val clipboardManager = LocalClipboardManager.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
    ) {
        Text(text = "Backend: $backendLabel")

        Row(modifier = Modifier.padding(top = 16.dp)) {
            Button(
                onClick = { onSetInferenceMode(MainViewModel.InferenceMode.LOCAL) },
                enabled = !busy && inferenceMode != MainViewModel.InferenceMode.LOCAL
            ) {
                Text("Local Mode")
            }

            OutlinedButton(
                onClick = { onSetInferenceMode(MainViewModel.InferenceMode.REMOTE) },
                enabled = !busy && inferenceMode != MainViewModel.InferenceMode.REMOTE,
                modifier = Modifier.padding(start = 8.dp)
            ) {
                Text("Remote Mode")
            }
        }

        Text(
            text = "Active mode: ${inferenceMode.name}",
            modifier = Modifier.padding(top = 8.dp)
        )

        if (inferenceMode == MainViewModel.InferenceMode.REMOTE) {
            OutlinedTextField(
                value = remoteServerUrl,
                onValueChange = onRemoteServerUrlChange,
                label = { Text("Remote Service URL (LAN IP on device)") },
                enabled = !busy,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(top = 8.dp)
            )

            if (remoteBackendLabel.isNotBlank()) {
                Text(
                    text = "Remote backend: $remoteBackendLabel",
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
        }

        Text(
            text = if (inferenceMode == MainViewModel.InferenceMode.LOCAL) {
                if (isModelLoaded) "Model: Loaded" else "Model: Not loaded"
            } else {
                "Model: Remote service managed"
            },
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

        if (diagnosticLogPath.isNotBlank()) {
            CopyableReadOnlyField(
                label = "Diagnostic Log Path",
                value = diagnosticLogPath,
                onCopy = { clipboardManager.setText(AnnotatedString(diagnosticLogPath)) },
                modifier = Modifier.padding(top = 8.dp)
            )
        }

        if (lastError.isNotBlank()) {
            CopyableReadOnlyField(
                label = "Last Error",
                value = lastError,
                onCopy = { clipboardManager.setText(AnnotatedString(lastError)) },
                modifier = Modifier.padding(top = 8.dp)
            )
        }

        if (inferenceMode == MainViewModel.InferenceMode.LOCAL) {
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
                        onClick = { onSelectModelCandidate(candidate.contentUri) },
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
        }

        TextField(
            value = prompt,
            onValueChange = { prompt = it },
            label = { Text("Prompt") },
            enabled = !busy && (isModelLoaded || inferenceMode == MainViewModel.InferenceMode.REMOTE),
            modifier = Modifier.padding(top = 16.dp)
        )

        Button(
            onClick = { onRun(prompt) },
            enabled = !busy && (isModelLoaded || inferenceMode == MainViewModel.InferenceMode.REMOTE),
            modifier = Modifier.padding(top = 16.dp)
        ) {
            Text(
                if (isGenerating) {
                    "Running..."
                } else if (inferenceMode == MainViewModel.InferenceMode.LOCAL) {
                    "Run Local"
                } else {
                    "Run Remote"
                }
            )
        }

        CopyableReadOnlyField(
            label = "Output",
            value = output,
            onCopy = { clipboardManager.setText(AnnotatedString(output)) },
            modifier = Modifier.padding(top = 16.dp)
        )

        CopyableReadOnlyField(
            label = "Event Log",
            value = eventLog,
            onCopy = { clipboardManager.setText(AnnotatedString(eventLog)) },
            modifier = Modifier.padding(top = 16.dp)
        )
    }
}

@Composable
private fun CopyableReadOnlyField(
    label: String,
    value: String,
    onCopy: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier.fillMaxWidth()) {
        Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
            Text(text = label)
            Button(onClick = onCopy) {
                Text("Copy")
            }
        }

        OutlinedTextField(
            value = value,
            onValueChange = {},
            readOnly = true,
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 8.dp),
            minLines = 4,
            maxLines = 12
        )
    }
}
