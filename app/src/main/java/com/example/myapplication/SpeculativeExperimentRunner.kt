package com.example.myapplication

import android.content.Context
import com.example.myapplication.inference.LocalLlmImpl
import com.example.myapplication.inference.RemoteInferenceClient
import com.example.myapplication.inference.SpeculativeCloseRequest
import com.example.myapplication.inference.SpeculativeProposeRequest
import com.example.myapplication.inference.SpeculativeStartRequest
import java.io.File
import java.util.UUID
import kotlin.math.max

object SpeculativeExperimentRunner {
    const val DEFAULT_BASE_URL = "http://127.0.0.1:8080"
    const val DEFAULT_PROMPT = "Explain speculative decoding briefly."
    const val DRAFT_MAX_TOKENS = 6
    const val INITIAL_DRAFT_TOKENS = 4
    const val ADAPTIVE_DRAFT_MIN_TOKENS = 1
    const val MIN_DRAFT_TOKENS = 1
    const val MAX_ACCEPTED_TOKENS = 64
    const val DRAFT_MODEL_NAME = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
    const val TARGET_MODEL_NAME = "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
    const val OUTPUT_NAME = "speculative-experiment-latest.txt"

    suspend fun run(
        context: Context,
        baseUrl: String,
        prompt: String,
        draftModelName: String = DRAFT_MODEL_NAME,
        targetModelName: String = TARGET_MODEL_NAME
    ): String {
        val localLlm = LocalLlmImpl(context)
        val remoteClient = RemoteInferenceClient()
        val modelPath = File(context.filesDir, "imported-models/$draftModelName")
        require(modelPath.exists()) { "Missing local draft model: ${modelPath.absolutePath}" }
        require(localLlm.loadModel(modelPath.absolutePath)) {
            "Failed to load local draft model at ${modelPath.absolutePath}: ${localLlm.lastError()}"
        }
        require(localLlm.supportsDraftSession()) { "Local draft sessions are unsupported on this device." }

        val health = remoteClient.health(baseUrl)
        val probe = remoteClient.probe(baseUrl)
        require(probe.speculativeVerifierMode == "llama_cpp_spec_split") {
            "Expected llama_cpp_spec_split verifier mode, got ${probe.speculativeVerifierMode}"
        }

        val startResponse = remoteClient.startSpeculativeSession(
            baseUrl = baseUrl,
            request = SpeculativeStartRequest(
                sessionId = UUID.randomUUID().toString(),
                requestId = UUID.randomUUID().toString(),
                draftModel = draftModelName,
                targetModel = targetModelName,
                userPrompt = prompt,
                temperature = 0.0,
                topP = 1.0
            )
        )

        val localDraftSession = localLlm.startDraftSession(
            systemPrompt = "",
            userPrompt = prompt,
            predictLength = MAX_ACCEPTED_TOKENS
        )

        val committedTokenIds = mutableListOf<Int>()
        val traces = mutableListOf<String>()
        var totalDraftFetchMs = 0L
        var totalRemoteProposeMs = 0L
        var totalLocalApplyMs = 0L
        var totalAcceptedTokens = 0
        var totalProposedTokens = 0
        val experimentStartedAt = System.currentTimeMillis()
        var closeStatus = "not_closed"
        var closeReason = ""
        var closeAcceptedText = ""

        var currentDraftMaxTokens = INITIAL_DRAFT_TOKENS
        var consecutiveZeroAcceptSteps = 0
        var consecutivePositiveAcceptSteps = 0
        var pendingVerifiedTokenIds = emptyList<Int>()

        try {
            for (draftStep in 1..128) {
                if (committedTokenIds.size >= MAX_ACCEPTED_TOKENS) {
                    break
                }

                val requestedDraftMaxTokens = currentDraftMaxTokens
                val draftFetchStartedAt = System.currentTimeMillis()
                val proposedTokenIds = if (pendingVerifiedTokenIds.isEmpty()) {
                    localLlm.draftNextRealTokenIds(
                        sessionId = localDraftSession.sessionId,
                        maxTokens = requestedDraftMaxTokens
                    )
                } else {
                    localLlm.applyVerifiedRealTokensAndDraftNextRealTokenIds(
                        sessionId = localDraftSession.sessionId,
                        tokenIds = pendingVerifiedTokenIds,
                        maxTokens = requestedDraftMaxTokens
                    )
                }
                val draftFetchMs = System.currentTimeMillis() - draftFetchStartedAt
                totalDraftFetchMs += draftFetchMs
                pendingVerifiedTokenIds = emptyList()

                if (proposedTokenIds.size < MIN_DRAFT_TOKENS) {
                    traces += "step=$draftStep stopped draftCount=${proposedTokenIds.size}"
                    break
                }

                totalProposedTokens += proposedTokenIds.size

                val proposeStartedAt = System.currentTimeMillis()
                val proposeResponse = remoteClient.proposeDraft(
                    baseUrl = baseUrl,
                    request = SpeculativeProposeRequest(
                        sessionId = startResponse.sessionId,
                        draftStep = draftStep,
                        proposedTokenIds = proposedTokenIds,
                        proposedText = "",
                        maxCorrectionTokens = 1,
                        draftTree = null
                    )
                )
                val remoteProposeMs = System.currentTimeMillis() - proposeStartedAt
                totalRemoteProposeMs += remoteProposeMs

                committedTokenIds += proposeResponse.acceptedTokenIds
                committedTokenIds += proposeResponse.correctionTokenIds
                totalAcceptedTokens += proposeResponse.acceptedTokenIds.size + proposeResponse.correctionTokenIds.size

                val acceptedDraftTokens = proposeResponse.acceptedCount
                if (acceptedDraftTokens == 0) {
                    consecutiveZeroAcceptSteps += 1
                    consecutivePositiveAcceptSteps = 0
                    currentDraftMaxTokens = max(
                        ADAPTIVE_DRAFT_MIN_TOKENS,
                        currentDraftMaxTokens / 2
                    )
                } else {
                    consecutiveZeroAcceptSteps = 0
                    consecutivePositiveAcceptSteps += 1
                    if (
                        consecutivePositiveAcceptSteps >= 2 &&
                        acceptedDraftTokens >= max(1, proposedTokenIds.size / 2)
                    ) {
                        currentDraftMaxTokens = minOf(DRAFT_MAX_TOKENS, currentDraftMaxTokens + 1)
                        consecutivePositiveAcceptSteps = 0
                    }
                }

                pendingVerifiedTokenIds = proposeResponse.acceptedTokenIds + proposeResponse.correctionTokenIds
                val localApplyStartedAt = System.currentTimeMillis()
                val localApplyMs = System.currentTimeMillis() - localApplyStartedAt
                totalLocalApplyMs += localApplyMs

                val estimatedTransportMs =
                    max(0.0, remoteProposeMs.toDouble() - proposeResponse.timingServiceTotalMs)
                traces += buildString {
                    append("step=$draftStep")
                    append(" draftMax=$requestedDraftMaxTokens")
                    append(" nextDraftMax=$currentDraftMaxTokens")
                    append(" proposed=${proposedTokenIds.size}")
                    append(" accepted=${proposeResponse.acceptedCount}")
                    append(" corrections=${proposeResponse.correctionTokenIds.size}")
                    append(" committed=${committedTokenIds.size}")
                    append(" zeroAcceptStreak=$consecutiveZeroAcceptSteps")
                    append(" positiveAcceptStreak=$consecutivePositiveAcceptSteps")
                    append(" draftFetchMs=$draftFetchMs")
                    append(" remoteMs=$remoteProposeMs")
                    append(" localApplyMs=$localApplyMs")
                    append(" prepareMs=${"%.3f".format(proposeResponse.timingPrepareMs)}")
                    append(" decodeMs=${"%.3f".format(proposeResponse.timingDecodeMs)}")
                    append(" sampleMs=${"%.3f".format(proposeResponse.timingSampleMs)}")
                    append(" rollbackMs=${"%.3f".format(proposeResponse.timingRollbackMs)}")
                    append(" helperTotalMs=${"%.3f".format(proposeResponse.timingHelperTotalMs)}")
                    append(" helperRoundTripMs=${"%.3f".format(proposeResponse.timingHelperRoundTripMs)}")
                    append(" serviceTotalMs=${"%.3f".format(proposeResponse.timingServiceTotalMs)}")
                    append(" estimatedTransportMs=${"%.3f".format(estimatedTransportMs)}")
                    append(" finish=${proposeResponse.finishReason}")
                }

                if (proposeResponse.finishReason.isNotBlank() || committedTokenIds.size >= MAX_ACCEPTED_TOKENS) {
                    break
                }
            }

            val closeResponse = remoteClient.closeSpeculativeSession(
                baseUrl = baseUrl,
                request = SpeculativeCloseRequest(
                    sessionId = startResponse.sessionId,
                    reason = "android_experiment_complete"
                )
            )
            closeStatus = closeResponse.status
            closeReason = closeResponse.reason
            closeAcceptedText = closeResponse.acceptedText
        } finally {
            runCatching { localLlm.closeDraftSession(localDraftSession.sessionId) }
            runCatching { localLlm.cleanup() }
        }

        val totalMs = System.currentTimeMillis() - experimentStartedAt
        val overallTokensPerSecond =
            if (totalMs > 0) committedTokenIds.size * 1000.0 / totalMs else 0.0
        val draftTokensPerSecond =
            if (totalDraftFetchMs > 0) totalProposedTokens * 1000.0 / totalDraftFetchMs else 0.0

        return buildString {
            appendLine("ANDROID_SPEC_EXPERIMENT")
            appendLine("health=$health")
            appendLine("verifierMode=${probe.speculativeVerifierMode}")
            appendLine("prompt=$prompt")
            appendLine("draftModel=$draftModelName")
            appendLine("targetModel=$targetModelName")
            appendLine("draftMaxTokens=$DRAFT_MAX_TOKENS")
            appendLine("initialDraftTokens=$INITIAL_DRAFT_TOKENS")
            appendLine("adaptiveDraftMinTokens=$ADAPTIVE_DRAFT_MIN_TOKENS")
            appendLine("maxAcceptedTokens=$MAX_ACCEPTED_TOKENS")
            appendLine("steps=${traces.size}")
            appendLine("committedTokens=${committedTokenIds.size}")
            appendLine("totalAcceptedTokens=$totalAcceptedTokens")
            appendLine("totalProposedTokens=$totalProposedTokens")
            appendLine("totalMs=$totalMs")
            appendLine("totalDraftFetchMs=$totalDraftFetchMs")
            appendLine("totalRemoteProposeMs=$totalRemoteProposeMs")
            appendLine("totalLocalApplyMs=$totalLocalApplyMs")
            appendLine("overallTokensPerSecond=${"%.3f".format(overallTokensPerSecond)}")
            appendLine("draftTokensPerSecond=${"%.3f".format(draftTokensPerSecond)}")
            appendLine("closeStatus=$closeStatus")
            appendLine("closeReason=$closeReason")
            appendLine("acceptedText=$closeAcceptedText")
            appendLine("traces:")
            traces.forEach { appendLine(it) }
        }.trim()
    }
}
