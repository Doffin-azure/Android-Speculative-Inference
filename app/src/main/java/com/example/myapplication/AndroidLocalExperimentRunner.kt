package com.example.myapplication

import android.content.Context
import android.util.Log
import com.example.myapplication.inference.LocalLlmImpl
import java.io.File

object AndroidLocalExperimentRunner {
    private const val TAG = "AndroidLocalExpRunner"
    const val OUTPUT_NAME = "android-local-experiment-latest.txt"
    private const val CORRECTION_TOKEN_A = 13
    private const val CORRECTION_TOKEN_B = 42

    suspend fun run(
        context: Context,
        prompt: String,
        modelName: String = SpeculativeExperimentRunner.TARGET_MODEL_NAME,
        maxGenerateTokens: Int = SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS,
        onProgress: ((String) -> Unit)? = null
    ): String {
        fun publishProgress(stage: String, detail: String) {
            val text = buildString {
                appendLine("ANDROID_LOCAL_EXPERIMENT_IN_PROGRESS")
                appendLine("stage=$stage")
                appendLine("detail=$detail")
                appendLine("prompt=$prompt")
                appendLine("model=$modelName")
            }.trim()
            Log.i(TAG, text)
            onProgress?.invoke(text)
        }

        val localLlm = LocalLlmImpl(context)
        val modelPath = File(context.filesDir, "imported-models/$modelName")
        require(modelPath.exists()) { "Missing local model: ${modelPath.absolutePath}" }

        val totalStartedAt = System.currentTimeMillis()
        val loadStartedAt = System.currentTimeMillis()
        publishProgress("load_model", "begin")
        require(localLlm.loadModel(modelPath.absolutePath)) {
            "Failed to load local model at ${modelPath.absolutePath}: ${localLlm.lastError()}"
        }
        val loadMs = System.currentTimeMillis() - loadStartedAt
        publishProgress("load_model", "done loadMs=$loadMs")

        val generateStartedAt = System.currentTimeMillis()
        publishProgress("plain_generate", "begin")
        val generatedPieces = localLlm.generateTokenPieces(prompt, maxGenerateTokens)
        val generatedText = generatedPieces.joinToString(separator = "")
        val generateMs = System.currentTimeMillis() - generateStartedAt
        publishProgress("plain_generate", "done generateMs=$generateMs")

        val outputTokens = generatedPieces.size
        val outputCodePoints = generatedText.codePointCount(0, generatedText.length)
        val outputWordsApprox = generatedText.trim().split(Regex("\\s+")).filter { it.isNotBlank() }.size
        val outputTokensPerSecond =
            if (generateMs > 0) outputTokens * 1000.0 / generateMs else 0.0
        val outputCodePointsPerSecond =
            if (generateMs > 0) outputCodePoints * 1000.0 / generateMs else 0.0

        val supportsDraftSession = localLlm.supportsDraftSession()
        val supportsSplitDraftControl = localLlm.supportsSplitDraftControl()
        var draftLoopSteps = 0
        var draftLoopProducedTokens = 0
        var draftLoopMs = 0L
        val draftLoopTraces = mutableListOf<String>()
        var correctionLoopSteps = 0
        var correctionLoopCommittedTokens = 0
        var correctionLoopMs = 0L
        val correctionLoopTraces = mutableListOf<String>()

        if (supportsDraftSession) {
            publishProgress("draft_loop_session", "begin")
            val session = localLlm.startDraftSession(
                systemPrompt = "",
                userPrompt = prompt,
                predictLength = maxGenerateTokens
            )
            try {
                val authoritativeTokenIds = mutableListOf<Int>()
                val draftLoopStartedAt = System.currentTimeMillis()
                for (step in 1..128) {
                    if (authoritativeTokenIds.size >= maxGenerateTokens) {
                        break
                    }
                    publishProgress("draft_loop_step", "step=$step committed=${authoritativeTokenIds.size}")
                    val stepStartedAt = System.currentTimeMillis()
                    val drafted = localLlm.syncAndDraftNextRealTokenIds(
                        sessionId = session.sessionId,
                        authoritativeTokenIds = authoritativeTokenIds,
                        maxTokens = SpeculativeExperimentRunner.DRAFT_MAX_TOKENS
                    )
                    val stepMs = System.currentTimeMillis() - stepStartedAt
                    draftLoopSteps += 1
                    if (drafted.isEmpty()) {
                        draftLoopTraces += "step=$step produced=0 stepMs=$stepMs"
                        break
                    }

                    val takeCount = minOf(
                        drafted.size,
                        maxGenerateTokens - authoritativeTokenIds.size
                    )
                    val acceptedIds = drafted.take(takeCount)
                    authoritativeTokenIds += acceptedIds
                    draftLoopProducedTokens += acceptedIds.size
                    draftLoopTraces += "step=$step produced=${drafted.size} committed=${authoritativeTokenIds.size} stepMs=$stepMs"
                    localLlm.applyVerifiedRealTokens(session.sessionId, acceptedIds)
                }
                draftLoopMs = System.currentTimeMillis() - draftLoopStartedAt
                publishProgress("draft_loop_session", "done steps=$draftLoopSteps committed=$draftLoopProducedTokens draftLoopMs=$draftLoopMs")
            } finally {
                runCatching { localLlm.closeDraftSession(session.sessionId) }
            }

            publishProgress("correction_loop_session", "begin")
            val correctionSession = localLlm.startDraftSession(
                systemPrompt = "",
                userPrompt = prompt,
                predictLength = maxGenerateTokens
            )
            try {
                val authoritativeTokenIds = mutableListOf<Int>()
                val correctionLoopStartedAt = System.currentTimeMillis()
                for (step in 1..16) {
                    publishProgress("correction_loop_step", "step=$step committed=${authoritativeTokenIds.size}")
                    val stepStartedAt = System.currentTimeMillis()
                    val drafted = localLlm.syncAndDraftNextRealTokenIds(
                        sessionId = correctionSession.sessionId,
                        authoritativeTokenIds = authoritativeTokenIds,
                        maxTokens = SpeculativeExperimentRunner.DRAFT_MAX_TOKENS
                    )
                    val stepMs = System.currentTimeMillis() - stepStartedAt
                    correctionLoopSteps += 1
                    if (drafted.isEmpty()) {
                        correctionLoopTraces += "step=$step produced=0 committed=${authoritativeTokenIds.size} stepMs=$stepMs"
                        break
                    }

                    val acceptedPrefix = drafted.take(1)
                    authoritativeTokenIds += acceptedPrefix
                    val correctionTokenId = chooseCorrectionTokenId(drafted)
                    authoritativeTokenIds += correctionTokenId
                    correctionLoopCommittedTokens = authoritativeTokenIds.size
                    correctionLoopTraces += buildString {
                        append("step=$step")
                        append(" produced=${drafted.size}")
                        append(" acceptedPrefix=${acceptedPrefix.size}")
                        append(" correctionTokenId=$correctionTokenId")
                        append(" committed=${authoritativeTokenIds.size}")
                        append(" stepMs=$stepMs")
                    }
                    if (authoritativeTokenIds.size >= maxGenerateTokens) {
                        break
                    }
                }
                correctionLoopMs = System.currentTimeMillis() - correctionLoopStartedAt
                publishProgress("correction_loop_session", "done steps=$correctionLoopSteps committed=$correctionLoopCommittedTokens correctionLoopMs=$correctionLoopMs")
            } finally {
                runCatching { localLlm.closeDraftSession(correctionSession.sessionId) }
            }
        }

        runCatching { localLlm.cleanup() }
        publishProgress("cleanup", "done")

        val totalMs = System.currentTimeMillis() - totalStartedAt
        val draftLoopTokensPerSecond =
            if (draftLoopMs > 0) draftLoopProducedTokens * 1000.0 / draftLoopMs else 0.0
        val correctionLoopTokensPerSecond =
            if (correctionLoopMs > 0) correctionLoopCommittedTokens * 1000.0 / correctionLoopMs else 0.0

        return buildString {
            appendLine("ANDROID_LOCAL_EXPERIMENT")
            appendLine("prompt=$prompt")
            appendLine("model=$modelName")
            appendLine("maxGenerateTokens=$maxGenerateTokens")
            appendLine("loadMs=$loadMs")
            appendLine("generateMs=$generateMs")
            appendLine("totalMs=$totalMs")
            appendLine("outputTokens=$outputTokens")
            appendLine("outputTokensPerSecond=${"%.3f".format(outputTokensPerSecond)}")
            appendLine("outputCodePoints=$outputCodePoints")
            appendLine("outputWordsApprox=$outputWordsApprox")
            appendLine("outputCodePointsPerSecond=${"%.3f".format(outputCodePointsPerSecond)}")
            appendLine("supportsDraftSession=$supportsDraftSession")
            appendLine("supportsSplitDraftControl=$supportsSplitDraftControl")
            appendLine("draftLoopChunkTokens=${SpeculativeExperimentRunner.DRAFT_MAX_TOKENS}")
            appendLine("draftLoopSteps=$draftLoopSteps")
            appendLine("draftLoopProducedTokens=$draftLoopProducedTokens")
            appendLine("draftLoopMs=$draftLoopMs")
            appendLine("draftLoopTokensPerSecond=${"%.3f".format(draftLoopTokensPerSecond)}")
            appendLine("correctionLoopSteps=$correctionLoopSteps")
            appendLine("correctionLoopCommittedTokens=$correctionLoopCommittedTokens")
            appendLine("correctionLoopMs=$correctionLoopMs")
            appendLine("correctionLoopTokensPerSecond=${"%.3f".format(correctionLoopTokensPerSecond)}")
            appendLine("generatedText=$generatedText")
            appendLine("draftLoopTraces:")
            draftLoopTraces.forEach { appendLine(it) }
            appendLine("correctionLoopTraces:")
            correctionLoopTraces.forEach { appendLine(it) }
        }.trim()
    }

    private fun chooseCorrectionTokenId(drafted: List<Int>): Int {
        val blocked = drafted.toSet()
        if (!blocked.contains(CORRECTION_TOKEN_A)) {
            return CORRECTION_TOKEN_A
        }
        if (!blocked.contains(CORRECTION_TOKEN_B)) {
            return CORRECTION_TOKEN_B
        }
        return (drafted.firstOrNull()?.plus(1) ?: CORRECTION_TOKEN_A).coerceAtLeast(0)
    }
}
