package com.example.myapplication

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.example.myapplication.inference.LocalLlmImpl
import com.example.myapplication.inference.RemoteInferenceClient
import com.example.myapplication.inference.SpeculativeCloseRequest
import com.example.myapplication.inference.SpeculativeProposeRequest
import com.example.myapplication.inference.SpeculativeStartRequest
import java.io.File
import java.util.UUID
import kotlin.math.max
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SpeculativeExperimentInstrumentedTest {
    companion object {
        private const val TAG = "SpecExpTest"
        private const val BASE_URL = "http://127.0.0.1:8080"
        private const val PROMPT = "Explain speculative decoding briefly."
        private const val DRAFT_MAX_TOKENS = 16
        private const val MIN_DRAFT_TOKENS = 4
        private const val MAX_ACCEPTED_TOKENS = 64
        private const val MODEL_NAME = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
    }

    @Test
    fun runAndroidSpeculativeExperiment() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val localLlm = LocalLlmImpl(context)
        val remoteClient = RemoteInferenceClient()
        val modelPath = File(context.filesDir, "imported-models/$MODEL_NAME")
        require(modelPath.exists()) { "Missing local draft model on device: ${modelPath.absolutePath}" }

        val loaded = localLlm.loadModel(modelPath.absolutePath)
        assertTrue("Failed to load local draft model at ${modelPath.absolutePath}", loaded)
        require(localLlm.supportsDraftSession()) { "Local draft session is not supported on this device." }

        val health = remoteClient.health(BASE_URL)
        val probe = remoteClient.probe(BASE_URL)
        require(probe.speculativeVerifierMode == "llama_cpp_spec_split") {
            "Expected llama_cpp_spec_split verifier mode, got ${probe.speculativeVerifierMode}"
        }

        val startResponse = remoteClient.startSpeculativeSession(
            baseUrl = BASE_URL,
            request = SpeculativeStartRequest(
                sessionId = UUID.randomUUID().toString(),
                requestId = UUID.randomUUID().toString(),
                draftModel = MODEL_NAME,
                targetModel = "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
                userPrompt = PROMPT,
                temperature = 0.0,
                topP = 1.0
            )
        )

        val localDraftSession = localLlm.startDraftSession(
            systemPrompt = "",
            userPrompt = PROMPT,
            predictLength = MAX_ACCEPTED_TOKENS
        )

        val committedTokenIds = mutableListOf<Int>()
        val traces = mutableListOf<String>()
        var totalDraftFetchMs = 0L
        var totalRemoteProposeMs = 0L
        var totalLocalApplyMs = 0L
        var totalAccepted = 0
        var totalProposed = 0
        val experimentStartedAt = System.currentTimeMillis()
        var closeStatus = "not_closed"
        var closeReason = ""

        try {
            for (draftStep in 1..128) {
                if (committedTokenIds.size >= MAX_ACCEPTED_TOKENS) {
                    break
                }

                val draftFetchStartedAt = System.currentTimeMillis()
                val proposedTokenIds = localLlm.syncAndDraftNextRealTokenIds(
                    sessionId = localDraftSession.sessionId,
                    authoritativeTokenIds = committedTokenIds,
                    maxTokens = DRAFT_MAX_TOKENS
                )
                val draftFetchMs = System.currentTimeMillis() - draftFetchStartedAt
                totalDraftFetchMs += draftFetchMs

                if (proposedTokenIds.size < MIN_DRAFT_TOKENS) {
                    traces += "step=$draftStep stopped draftCount=${proposedTokenIds.size}"
                    break
                }

                totalProposed += proposedTokenIds.size

                val proposeStartedAt = System.currentTimeMillis()
                val proposeResponse = remoteClient.proposeDraft(
                    baseUrl = BASE_URL,
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
                totalAccepted += proposeResponse.acceptedTokenIds.size + proposeResponse.correctionTokenIds.size

                val localApplyStartedAt = System.currentTimeMillis()
                val appliedCount = committedTokenIds.size
                val localApplyMs = System.currentTimeMillis() - localApplyStartedAt
                totalLocalApplyMs += localApplyMs

                val estimatedTransportMs =
                    max(0.0, remoteProposeMs.toDouble() - proposeResponse.timingServiceTotalMs)
                traces += buildString {
                    append("step=$draftStep")
                    append(" proposed=${proposedTokenIds.size}")
                    append(" accepted=${proposeResponse.acceptedCount}")
                    append(" corrections=${proposeResponse.correctionTokenIds.size}")
                    append(" committed=$appliedCount")
                    append(" draftFetchMs=$draftFetchMs")
                    append(" remoteMs=$remoteProposeMs")
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

                if (proposeResponse.finishReason.isNotBlank() ||
                    committedTokenIds.size >= MAX_ACCEPTED_TOKENS
                ) {
                    break
                }
            }

            val closeResponse = remoteClient.closeSpeculativeSession(
                baseUrl = BASE_URL,
                request = SpeculativeCloseRequest(
                    sessionId = startResponse.sessionId,
                    reason = "android_experiment_complete"
                )
            )
            closeStatus = closeResponse.status
            closeReason = closeResponse.reason
        } finally {
            runCatching { localLlm.closeDraftSession(localDraftSession.sessionId) }
            runCatching { localLlm.cleanup() }
        }

        val totalMs = System.currentTimeMillis() - experimentStartedAt
        val overallTokensPerSecond =
            if (totalMs > 0) committedTokenIds.size * 1000.0 / totalMs else 0.0
        val draftTokensPerSecond =
            if (totalDraftFetchMs > 0) totalProposed * 1000.0 / totalDraftFetchMs else 0.0

        val summary = buildString {
            appendLine("ANDROID_SPEC_EXPERIMENT")
            appendLine("health=$health")
            appendLine("verifierMode=${probe.speculativeVerifierMode}")
            appendLine("backend=${probe.llamaServerBaseUrl}")
            appendLine("prompt=$PROMPT")
            appendLine("draftModel=$MODEL_NAME")
            appendLine("targetModel=Llama-3.2-3B-Instruct-Q4_K_M.gguf")
            appendLine("draftMaxTokens=$DRAFT_MAX_TOKENS")
            appendLine("maxAcceptedTokens=$MAX_ACCEPTED_TOKENS")
            appendLine("steps=${traces.size}")
            appendLine("committedTokens=${committedTokenIds.size}")
            appendLine("totalAcceptedTokens=$totalAccepted")
            appendLine("totalProposedTokens=$totalProposed")
            appendLine("totalMs=$totalMs")
            appendLine("totalDraftFetchMs=$totalDraftFetchMs")
            appendLine("totalRemoteProposeMs=$totalRemoteProposeMs")
            appendLine("totalLocalApplyMs=$totalLocalApplyMs")
            appendLine("overallTokensPerSecond=${"%.3f".format(overallTokensPerSecond)}")
            appendLine("draftTokensPerSecond=${"%.3f".format(draftTokensPerSecond)}")
            appendLine("closeStatus=$closeStatus")
            appendLine("closeReason=$closeReason")
            appendLine("traces:")
            traces.forEach { appendLine(it) }
        }.trim()

        Log.i(TAG, summary)
        println(summary)
    }
}
