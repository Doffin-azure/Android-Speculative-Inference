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
import androidx.compose.material3.Checkbox
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
    remoteProbeSummary: String,
    remoteResultSummary: String,
    speculativeSessionSummary: String,
    speculativeForceMismatch: Boolean,
    speculativeVerifierMode: String,
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
    onSetSpeculativeForceMismatch: (Boolean) -> Unit,
    onTestRemoteConnectivity: () -> Unit,
    onSelectModelCandidate: (String) -> Unit,
    onLoadModel: () -> Unit,
    onRunDraftRuntimeProbeDemo: (String) -> Unit,
    onRun: (String) -> Unit
) {
    var prompt by remember {
        mutableStateOf(
            """
            You are a precise technical assistant. Please answer in clear English with short paragraphs and compact bullet points when helpful.

            Task:
            Explain speculative decoding for large language models in a practical engineering way.

            Please cover all of the following:
            1. What speculative decoding is.
            2. Why it can improve latency.
            3. The difference between draft model and target model.
            4. What “accept the longest matching prefix” means.
            5. Why a verifier may append one extra target token after a fully accepted draft.
            6. What kinds of implementation overhead can reduce the speedup in real systems.
            7. The difference between theoretical speedup and end-to-end wall-clock speedup.
            8. Why cross-device speculative decoding can be harder than single-process speculative decoding.
            9. A short list of the main bottlenecks in a mobile-draft plus desktop-verifier architecture.
            10. A brief concluding summary.

            Requirements:
            - Write at least 10 paragraphs.
            - Include one short bullet list near the end.
            - Keep the explanation concrete and engineering-oriented rather than academic.
            - Do not ask follow-up questions.
            """.trimIndent()
        )
    }
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

            OutlinedButton(
                onClick = { onSetInferenceMode(MainViewModel.InferenceMode.SPECULATIVE) },
                enabled = !busy && inferenceMode != MainViewModel.InferenceMode.SPECULATIVE,
                modifier = Modifier.padding(start = 8.dp)
            ) {
                Text("Speculative Mode")
            }
        }

        Text(
            text = "Active mode: ${inferenceMode.name}",
            modifier = Modifier.padding(top = 8.dp)
        )

        if (speculativeVerifierMode.isNotBlank()) {
            Text(
                text = "Speculative verifier mode: $speculativeVerifierMode",
                modifier = Modifier.padding(top = 8.dp)
            )
        }

        if (inferenceMode != MainViewModel.InferenceMode.LOCAL) {
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

            Button(
                onClick = onTestRemoteConnectivity,
                enabled = !busy,
                modifier = Modifier.padding(top = 8.dp)
            ) {
                Text("Test Remote Connectivity")
            }

            if (remoteProbeSummary.isNotBlank()) {
                CopyableReadOnlyField(
                    label = "Remote Probe",
                    value = remoteProbeSummary,
                    onCopy = { clipboardManager.setText(AnnotatedString(remoteProbeSummary)) },
                    modifier = Modifier.padding(top = 8.dp)
                )
            }

            if (remoteResultSummary.isNotBlank()) {
                CopyableReadOnlyField(
                    label = "Remote Result",
                    value = remoteResultSummary,
                    onCopy = { clipboardManager.setText(AnnotatedString(remoteResultSummary)) },
                    modifier = Modifier.padding(top = 8.dp)
                )
            }

            if (inferenceMode == MainViewModel.InferenceMode.SPECULATIVE && speculativeSessionSummary.isNotBlank()) {
                CopyableReadOnlyField(
                    label = "Speculative Session",
                    value = speculativeSessionSummary,
                    onCopy = { clipboardManager.setText(AnnotatedString(speculativeSessionSummary)) },
                    modifier = Modifier.padding(top = 8.dp)
                )
            }

            if (inferenceMode == MainViewModel.InferenceMode.SPECULATIVE) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text("Force mismatch for verify test")
                    Checkbox(
                        checked = speculativeForceMismatch,
                        onCheckedChange = { onSetSpeculativeForceMismatch(it) },
                        enabled = !busy
                    )
                }
            }
        }

        Text(
            text = if (inferenceMode == MainViewModel.InferenceMode.LOCAL) {
                if (isModelLoaded) "Model: Loaded" else "Model: Not loaded"
            } else if (inferenceMode == MainViewModel.InferenceMode.REMOTE) {
                "Model: Remote service managed"
            } else {
                "Model: Local draft + remote verify"
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

            if (isModelLoaded) {
                OutlinedButton(
                    onClick = { onRunDraftRuntimeProbeDemo(prompt) },
                    enabled = !busy,
                    modifier = Modifier.padding(top = 8.dp)
                ) {
                    Text("Run Draft Probe Demo")
                }
            }
        }

        TextField(
            value = prompt,
            onValueChange = { prompt = it },
            label = { Text("Prompt") },
            enabled = !busy && (isModelLoaded || inferenceMode != MainViewModel.InferenceMode.LOCAL),
            modifier = Modifier.padding(top = 16.dp)
        )

        Button(
            onClick = { onRun(prompt) },
            enabled = !busy && (isModelLoaded || inferenceMode != MainViewModel.InferenceMode.LOCAL),
            modifier = Modifier.padding(top = 16.dp)
        ) {
            Text(
                if (isGenerating) {
                    "Running..."
                } else if (inferenceMode == MainViewModel.InferenceMode.LOCAL) {
                    "Run Local"
                } else if (inferenceMode == MainViewModel.InferenceMode.REMOTE) {
                    "Run Remote"
                } else {
                    "Run Speculative"
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
