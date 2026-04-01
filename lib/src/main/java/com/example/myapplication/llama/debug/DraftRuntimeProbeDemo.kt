package com.example.myapplication.llama.debug

import android.content.Context
import com.example.myapplication.llama.AiChat
import com.example.myapplication.llama.InferenceEngine

class DraftRuntimeProbeDemo(private val context: Context) {
    private val engine: InferenceEngine = AiChat.getInferenceEngine(context.applicationContext)

    private external fun nativeCaptureTopKJson(topK: Int): String

    private external fun nativeRunStateRoundTripJson(topK: Int): String

    private external fun nativeRunSequenceStateRoundTripJson(topK: Int): String

    suspend fun runTopKAndStateRoundTripDemo(
        modelPath: String,
        userPrompt: String,
        systemPrompt: String = "",
        topK: Int = 5,
        predictLength: Int = 32,
        treeDepth: Int = 4,
        treeBranchFactor: Int = 3
    ): String {
        require(modelPath.isNotBlank()) { "modelPath cannot be blank." }
        require(userPrompt.isNotBlank()) { "userPrompt cannot be blank." }
        require(topK > 0) { "topK must be > 0." }
        require(treeDepth > 0) { "treeDepth must be > 0." }
        require(treeBranchFactor > 0) { "treeBranchFactor must be > 0." }

        if (engine.loadedModelPath() != modelPath || !engine.isModelLoaded()) {
            engine.loadModel(modelPath)
        }

        val session = engine.startDraftSession(
            systemPrompt = systemPrompt,
            userPrompt = userPrompt,
            predictLength = predictLength
        )

        return try {
            val topKJson = nativeCaptureTopKJson(topK)
            val roundTripJson = nativeRunStateRoundTripJson(topK)
            val seqRoundTripJson = nativeRunSequenceStateRoundTripJson(topK)
            val treeProposal = if (engine.supportsDraftTree()) {
                engine.draftTreeProposal(
                    sessionId = session.sessionId,
                    maxDepth = treeDepth,
                    branchFactor = treeBranchFactor
                )
            } else {
                null
            }
            buildString {
                appendLine("Draft runtime probe demo")
                appendLine("sessionId=${session.sessionId}")
                appendLine("topK=$topK")
                appendLine("capture=$topKJson")
                appendLine("roundTrip=$roundTripJson")
                appendLine("sequenceRoundTrip=$seqRoundTripJson")
                if (treeProposal != null) {
                    appendLine("treeDepth=$treeDepth")
                    appendLine("treeBranchFactor=$treeBranchFactor")
                    appendLine("treeNodeCount=${treeProposal.nodeCount}")
                    appendLine("treeDepthEvaluated=${treeProposal.depthEvaluated}")
                    appendLine("treeBestPathTokenIds=${treeProposal.bestPathTokenIds.joinToString()}")
                    appendLine("treeBestPathNodeIndices=${treeProposal.bestPathNodeIndices.joinToString()}")
                    appendLine("treeBestPathText=${treeProposal.bestPathText}")
                    appendLine(
                        "treeNodesPreview=" + treeProposal.nodes
                            .take(8)
                            .joinToString(" | ") { node ->
                                "idx=${node.nodeIndex},depth=${node.depth},parent=${node.parentNodeIndex},token=${node.tokenText},p=${node.probability},cum=${node.cumulativeLogProbability}"
                            }
                    )
                }
            }.trim()
        } finally {
            engine.closeDraftSession(session.sessionId)
        }
    }

    companion object {
        init {
            runCatching { System.loadLibrary("ai-chat") }
        }
    }
}
