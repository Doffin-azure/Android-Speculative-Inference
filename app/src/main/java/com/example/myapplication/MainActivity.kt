package com.example.myapplication

import android.net.Uri
import android.os.Bundle
import android.os.Build
import android.util.Log
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.activity.result.contract.ActivityResultContracts
import androidx.lifecycle.lifecycleScope
import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import com.example.myapplication.ui.MainScreen
import com.example.myapplication.viewmodel.MainViewModel
import java.io.File
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    companion object {
        private const val TAG = "MainActivity"
        private const val EXTRA_AUTOMATION_ACTION = "automationAction"
        private const val ACTION_ANDROID_LOCAL_EXPERIMENT = "android_local_experiment"
        private const val ACTION_ANDROID_SPEC_EXPERIMENT = "android_spec_experiment"
    }

    private val viewModel: MainViewModel by viewModels()
    private var automationJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
        }
        @Suppress("DEPRECATION")
        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
        )
        maybeStartAutomation(intent)

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
            val speculativeSessionSummary by viewModel.speculativeSessionSummary.collectAsState()
            val speculativeForceMismatch by viewModel.speculativeForceMismatch.collectAsState()
            val speculativeVerifierMode by viewModel.speculativeVerifierMode.collectAsState()
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
                speculativeSessionSummary = speculativeSessionSummary,
                speculativeForceMismatch = speculativeForceMismatch,
                speculativeVerifierMode = speculativeVerifierMode,
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
                onSetSpeculativeForceMismatch = viewModel::setSpeculativeForceMismatch,
                onTestRemoteConnectivity = viewModel::testRemoteConnectivity,
                onSelectModelCandidate = viewModel::selectModelCandidate,
                onLoadModel = { viewModel.loadModel() },
                onRunDraftRuntimeProbeDemo = { prompt -> viewModel.runDraftRuntimeProbeDemo(prompt) },
                onRun = { prompt -> viewModel.runInference(prompt) }
            )
        }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        maybeStartAutomation(intent)
    }

    private fun maybeStartAutomation(intent: android.content.Intent?) {
        val safeIntent = intent ?: return
        val action = safeIntent.getStringExtra(EXTRA_AUTOMATION_ACTION).orEmpty()
        if (action.isBlank()) {
            return
        }
        automationJob?.cancel()
        automationJob = lifecycleScope.launch {
            when (action) {
                ACTION_ANDROID_LOCAL_EXPERIMENT -> runAndroidLocalExperiment(safeIntent)
                ACTION_ANDROID_SPEC_EXPERIMENT -> runAndroidSpecExperiment(safeIntent)
                else -> Log.w(TAG, "Unknown automation action: $action")
            }
            finish()
        }
    }

    private suspend fun runAndroidLocalExperiment(intent: android.content.Intent) {
        val prompt = intent.getStringExtra("prompt").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DEFAULT_PROMPT
        }
        val modelName = intent.getStringExtra("modelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.TARGET_MODEL_NAME
        }
        val maxGenerateTokens = intent.getIntExtra(
            "maxGenerateTokens",
            SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS
        )
        val outputFile = File(filesDir, "logs/${AndroidLocalExperimentRunner.OUTPUT_NAME}")
        outputFile.parentFile?.mkdirs()
        runCatching {
            val summary = AndroidLocalExperimentRunner.run(
                context = applicationContext,
                prompt = prompt,
                modelName = modelName,
                maxGenerateTokens = maxGenerateTokens
            ) { progress ->
                outputFile.writeText(progress)
            }
            outputFile.writeText(summary)
            Log.i(TAG, "Android local automation completed")
        }.onFailure { throwable ->
            val failure = buildString {
                appendLine("ANDROID_LOCAL_EXPERIMENT_FAILED")
                appendLine("error=${throwable::class.java.name}: ${throwable.message.orEmpty()}")
                appendLine(Log.getStackTraceString(throwable))
            }.trim()
            outputFile.writeText(failure)
            Log.e(TAG, failure)
        }
    }

    private suspend fun runAndroidSpecExperiment(intent: android.content.Intent) {
        val baseUrl = intent.getStringExtra("baseUrl").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DEFAULT_BASE_URL
        }
        val prompt = intent.getStringExtra("prompt").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DEFAULT_PROMPT
        }
        val draftModelName = intent.getStringExtra("draftModelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.DRAFT_MODEL_NAME
        }
        val targetModelName = intent.getStringExtra("targetModelName").orEmpty().ifBlank {
            SpeculativeExperimentRunner.TARGET_MODEL_NAME
        }
        val maxAcceptedTokens = intent.getIntExtra(
            "maxAcceptedTokens",
            SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS
        )
        val draftMaxTokens = intent.getIntExtra("draftMaxTokens", SpeculativeExperimentRunner.DRAFT_MAX_TOKENS)
        val initialDraftTokens = intent.getIntExtra("initialDraftTokens", draftMaxTokens)
        val draftMinTokens = intent.getIntExtra("draftMinTokens", SpeculativeExperimentRunner.DRAFT_MIN_TOKENS)
        val draftMinProb = if (intent.hasExtra("draftMinProb")) {
            intent.getFloatExtra(
                "draftMinProb",
                SpeculativeExperimentRunner.DRAFT_MIN_PROB_UNSUPPORTED.toFloat()
            ).toDouble()
        } else {
            SpeculativeExperimentRunner.DRAFT_MIN_PROB_UNSUPPORTED
        }
        val adaptiveDraftingEnabled = intent.getBooleanExtra("adaptiveDraftingEnabled", false)
        val adaptiveDraftMinTokens = intent.getIntExtra(
            "adaptiveDraftMinTokens",
            SpeculativeExperimentRunner.ADAPTIVE_DRAFT_MIN_TOKENS
        )

        val outputFile = File(filesDir, "logs/${SpeculativeExperimentRunner.OUTPUT_NAME}")
        outputFile.parentFile?.mkdirs()
        runCatching {
            val summary = SpeculativeExperimentRunner.run(
                context = applicationContext,
                baseUrl = baseUrl,
                prompt = prompt,
                draftModelName = draftModelName,
                targetModelName = targetModelName,
                maxAcceptedTokens = maxAcceptedTokens,
                draftMaxTokens = draftMaxTokens,
                initialDraftTokens = initialDraftTokens,
                draftMinTokens = draftMinTokens,
                draftMinProb = draftMinProb,
                adaptiveDraftingEnabled = adaptiveDraftingEnabled,
                adaptiveDraftMinTokens = adaptiveDraftMinTokens,
                onProgress = { progress ->
                    outputFile.writeText(progress)
                }
            )
            outputFile.writeText(summary)
            Log.i(TAG, "Android speculative automation completed")
        }.onFailure { throwable ->
            val failure = buildString {
                appendLine("ANDROID_SPEC_EXPERIMENT_FAILED")
                appendLine("error=${throwable::class.java.name}: ${throwable.message.orEmpty()}")
                appendLine(Log.getStackTraceString(throwable))
            }.trim()
            outputFile.writeText(failure)
            Log.e(TAG, failure)
        }
    }
}
