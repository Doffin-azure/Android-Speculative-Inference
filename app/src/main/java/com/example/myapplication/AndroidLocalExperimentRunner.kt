package com.example.myapplication

import android.content.Context
import com.example.myapplication.inference.LocalLlmImpl
import java.io.File

object AndroidLocalExperimentRunner {
    const val OUTPUT_NAME = "android-local-experiment-latest.txt"

    suspend fun run(context: Context, prompt: String): String {
        val localLlm = LocalLlmImpl(context)
        val modelPath = File(context.filesDir, "imported-models/${SpeculativeExperimentRunner.DRAFT_MODEL_NAME}")
        require(modelPath.exists()) { "Missing local model: ${modelPath.absolutePath}" }

        val totalStartedAt = System.currentTimeMillis()
        val loadStartedAt = System.currentTimeMillis()
        require(localLlm.loadModel(modelPath.absolutePath)) {
            "Failed to load local model at ${modelPath.absolutePath}: ${localLlm.lastError()}"
        }
        val loadMs = System.currentTimeMillis() - loadStartedAt

        val generateStartedAt = System.currentTimeMillis()
        val generatedText = localLlm.generate(prompt, SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS)
        val generateMs = System.currentTimeMillis() - generateStartedAt

        val outputCodePoints = generatedText.codePointCount(0, generatedText.length)
        val outputWordsApprox = generatedText.trim().split(Regex("\\s+")).filter { it.isNotBlank() }.size
        val outputCodePointsPerSecond =
            if (generateMs > 0) outputCodePoints * 1000.0 / generateMs else 0.0

        val supportsDraftSession = localLlm.supportsDraftSession()
        val supportsSplitDraftControl = localLlm.supportsSplitDraftControl()
        var draftLoopSteps = 0
        var draftLoopProducedTokens = 0
        var draftLoopMs = 0L
        val draftLoopTraces = mutableListOf<String>()

        if (supportsDraftSession) {
            val session = localLlm.startDraftSession(
                systemPrompt = "",
                userPrompt = prompt,
                predictLength = SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS
            )
            try {
                val authoritativeTokenIds = mutableListOf<Int>()
                val draftLoopStartedAt = System.currentTimeMillis()
                for (step in 1..128) {
                    if (authoritativeTokenIds.size >= SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS) {
                        break
                    }
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
                        SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS - authoritativeTokenIds.size
                    )
                    val acceptedIds = drafted.take(takeCount)
                    authoritativeTokenIds += acceptedIds
                    draftLoopProducedTokens += acceptedIds.size
                    draftLoopTraces += "step=$step produced=${drafted.size} committed=${authoritativeTokenIds.size} stepMs=$stepMs"
                    localLlm.applyVerifiedRealTokens(session.sessionId, acceptedIds)
                }
                draftLoopMs = System.currentTimeMillis() - draftLoopStartedAt
            } finally {
                runCatching { localLlm.closeDraftSession(session.sessionId) }
            }
        }

        runCatching { localLlm.cleanup() }

        val totalMs = System.currentTimeMillis() - totalStartedAt
        val draftLoopTokensPerSecond =
            if (draftLoopMs > 0) draftLoopProducedTokens * 1000.0 / draftLoopMs else 0.0

        return buildString {
            appendLine("ANDROID_LOCAL_EXPERIMENT")
            appendLine("prompt=$prompt")
            appendLine("model=${SpeculativeExperimentRunner.DRAFT_MODEL_NAME}")
            appendLine("maxGenerateTokens=${SpeculativeExperimentRunner.MAX_ACCEPTED_TOKENS}")
            appendLine("loadMs=$loadMs")
            appendLine("generateMs=$generateMs")
            appendLine("totalMs=$totalMs")
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
            appendLine("generatedText=$generatedText")
            appendLine("draftLoopTraces:")
            draftLoopTraces.forEach { appendLine(it) }
        }.trim()
    }
}
