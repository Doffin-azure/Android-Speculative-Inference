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
    const val DEFAULT_SEED = 1234
    const val DRAFT_MAX_TOKENS = 16
    const val INITIAL_DRAFT_TOKENS = DRAFT_MAX_TOKENS
    const val DRAFT_MIN_TOKENS = 0
    const val DRAFT_MIN_PROB_UNSUPPORTED = -1.0
    const val ADAPTIVE_DRAFT_MIN_TOKENS = DRAFT_MAX_TOKENS
    const val MAX_ACCEPTED_TOKENS = 64
    const val DRAFT_MODEL_NAME = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
    const val TARGET_MODEL_NAME = "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
    const val OUTPUT_NAME = "speculative-experiment-latest.txt"
    private const val MAX_EXPERIMENT_STEPS = 2048

    suspend fun run(
        context: Context,
        baseUrl: String,
        prompt: String,
        draftModelName: String = DRAFT_MODEL_NAME,
        targetModelName: String = TARGET_MODEL_NAME,
        maxAcceptedTokens: Int = MAX_ACCEPTED_TOKENS,
        draftMaxTokens: Int = DRAFT_MAX_TOKENS,
        initialDraftTokens: Int = INITIAL_DRAFT_TOKENS,
        draftMinTokens: Int = DRAFT_MIN_TOKENS,
        draftMinProb: Double = DRAFT_MIN_PROB_UNSUPPORTED,
        adaptiveDraftingEnabled: Boolean = false,
        adaptiveDraftMinTokens: Int = ADAPTIVE_DRAFT_MIN_TOKENS,
        onProgress: ((String) -> Unit)? = null
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
                topP = 1.0,
                topK = 1,
                seed = DEFAULT_SEED
            )
        )

        val normalizedMaxAcceptedTokens = maxAcceptedTokens.coerceAtLeast(1)

        val localDraftSession = localLlm.startDraftSession(
            systemPrompt = "",
            userPrompt = prompt,
            predictLength = normalizedMaxAcceptedTokens,
            draftMinProb = draftMinProb.toFloat()
        )

        val committedTokenIds = mutableListOf<Int>()
        val traces = mutableListOf<String>()
        var totalDraftFetchMs = 0L
        var totalDraftGenerateMs = 0L
        var totalRemoteProposeMs = 0L
        var totalLocalApplyMs = 0L
        var totalAcceptedTokens = 0
        var totalProposedTokens = 0
        val experimentStartedAt = System.currentTimeMillis()
        var closeStatus = "not_closed"
        var closeReason = ""
        var closeAcceptedText = ""

        val normalizedDraftMaxTokens = draftMaxTokens.coerceAtLeast(1)
        val normalizedInitialDraftTokens = initialDraftTokens.coerceIn(1, normalizedDraftMaxTokens)
        val normalizedDraftMinTokens = draftMinTokens.coerceAtLeast(0)
        val draftProbabilityThresholdSupported = draftMinProb >= 0.0
        val strategyMode = if (draftProbabilityThresholdSupported) {
            "native_probability_threshold_with_max_cap"
        } else {
            "fixed_draft_length_aligned_to_native_split"
        }
        try {
            for (draftStep in 1..MAX_EXPERIMENT_STEPS) {
                if (committedTokenIds.size >= normalizedMaxAcceptedTokens) {
                    break
                }

                val requestedDraftMaxTokens = if (draftStep == 1) {
                    normalizedInitialDraftTokens
                } else {
                    normalizedDraftMaxTokens
                }
                val draftFetchStartedAt = System.currentTimeMillis()
                val proposedTokenIds = localLlm.syncAndDraftNextRealTokenIds(
                    sessionId = localDraftSession.sessionId,
                    authoritativeTokenIds = committedTokenIds,
                    maxTokens = requestedDraftMaxTokens
                )
                val draftGenerateMs = System.currentTimeMillis() - draftFetchStartedAt
                totalDraftGenerateMs += draftGenerateMs
                val localApplyMs = 0L
                val draftFetchMs = draftGenerateMs
                totalDraftFetchMs += draftFetchMs

                if (proposedTokenIds.isEmpty()) {
                    traces += "step=$draftStep stopped draftCount=0 draftMinTokens=$normalizedDraftMinTokens"
                    break
                }

                if (proposedTokenIds.size < normalizedDraftMinTokens) {
                    traces += "step=$draftStep stopped draftCount=${proposedTokenIds.size} draftMinTokens=$normalizedDraftMinTokens"
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

                val remainingCapacity = (normalizedMaxAcceptedTokens - committedTokenIds.size).coerceAtLeast(0)
                val acceptedToCommit = proposeResponse.acceptedTokenIds.take(remainingCapacity)
                val correctionsToCommit = proposeResponse.correctionTokenIds.take(
                    (normalizedMaxAcceptedTokens - committedTokenIds.size - acceptedToCommit.size).coerceAtLeast(0)
                )

                committedTokenIds += acceptedToCommit
                committedTokenIds += correctionsToCommit
                totalAcceptedTokens += acceptedToCommit.size + correctionsToCommit.size

                val estimatedTransportMs =
                    max(0.0, remoteProposeMs.toDouble() - proposeResponse.timingServiceTotalMs)
                val traceLine = buildString {
                    append("step=$draftStep")
                    append(" draftMax=$requestedDraftMaxTokens")
                    append(" proposed=${proposedTokenIds.size}")
                    append(" accepted=${acceptedToCommit.size}")
                    append(" corrections=${correctionsToCommit.size}")
                    append(" committed=${committedTokenIds.size}")
                    append(" draftFetchMs=$draftFetchMs")
                    append(" draftGenerateMs=$draftGenerateMs")
                    append(" draftRollbackMs=$localApplyMs")
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
                traces += traceLine
                onProgress?.invoke(
                    buildString {
                        appendLine("ANDROID_SPEC_EXPERIMENT_IN_PROGRESS")
                        appendLine("prompt=$prompt")
                        appendLine("timingBasis=steady_state_after_local_and_remote_sessions_ready_before_first_draft")
                        appendLine("draftModel=$draftModelName")
                        appendLine("targetModel=$targetModelName")
                        appendLine("draftMaxTokens=$normalizedDraftMaxTokens")
                        appendLine("initialDraftTokens=$normalizedInitialDraftTokens")
                        appendLine("draftMinTokens=$normalizedDraftMinTokens")
                        appendLine("draftMinProb=$draftMinProb")
                        appendLine("draftProbabilityThresholdSupported=$draftProbabilityThresholdSupported")
                        appendLine("strategyMode=$strategyMode")
                        appendLine("adaptiveDraftingEnabled=$adaptiveDraftingEnabled")
                        appendLine("adaptiveDraftMinTokens=$adaptiveDraftMinTokens")
                        appendLine("seed=$DEFAULT_SEED")
                        appendLine("stepsCompleted=${traces.size}")
                        appendLine("committedTokens=${committedTokenIds.size}")
                        appendLine("totalDraftFetchMs=$totalDraftFetchMs")
                        appendLine("totalDraftGenerateMs=$totalDraftGenerateMs")
                        appendLine("totalDraftRollbackMs=$totalLocalApplyMs")
                        appendLine("totalRemoteProposeMs=$totalRemoteProposeMs")
                        appendLine("latestTrace=$traceLine")
                    }.trim()
                )

                if (proposeResponse.finishReason.isNotBlank() || committedTokenIds.size >= normalizedMaxAcceptedTokens) {
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
            appendLine("timingBasis=steady_state_after_local_and_remote_sessions_ready_before_first_draft")
            appendLine("draftModel=$draftModelName")
            appendLine("targetModel=$targetModelName")
            appendLine("draftMaxTokens=$normalizedDraftMaxTokens")
            appendLine("initialDraftTokens=$normalizedInitialDraftTokens")
            appendLine("draftMinTokens=$normalizedDraftMinTokens")
            appendLine("draftMinProb=$draftMinProb")
            appendLine("draftProbabilityThresholdSupported=$draftProbabilityThresholdSupported")
            appendLine("strategyMode=$strategyMode")
            appendLine("adaptiveDraftingEnabled=$adaptiveDraftingEnabled")
            appendLine("adaptiveDraftMinTokens=$adaptiveDraftMinTokens")
            appendLine("seed=$DEFAULT_SEED")
            appendLine("maxAcceptedTokens=$normalizedMaxAcceptedTokens")
            appendLine("steps=${traces.size}")
            appendLine("committedTokens=${committedTokenIds.size}")
            appendLine("totalAcceptedTokens=$totalAcceptedTokens")
            appendLine("totalProposedTokens=$totalProposedTokens")
            appendLine("totalMs=$totalMs")
            appendLine("totalDraftFetchMs=$totalDraftFetchMs")
            appendLine("totalDraftGenerateMs=$totalDraftGenerateMs")
            appendLine("totalDraftRollbackMs=$totalLocalApplyMs")
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
