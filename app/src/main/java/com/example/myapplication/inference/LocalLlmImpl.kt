package com.example.myapplication.inference

import android.content.Context
import com.example.myapplication.llama.DraftSessionHandle
import com.example.myapplication.llama.DraftTreeProposal
import com.example.myapplication.llama.AiChat
import com.example.myapplication.llama.InferenceEngine
import kotlinx.coroutines.flow.toList

class LocalLlmImpl(context: Context) : LocalLlm {
    private val engine: InferenceEngine = AiChat.getInferenceEngine(context.applicationContext)

    override fun backendLabel(): String {
        return engine.backendLabel()
    }

    override fun isModelLoaded(): Boolean {
        return engine.isModelLoaded()
    }

    override fun loadedModelPath(): String {
        return engine.loadedModelPath()
    }

    override fun lastError(): String {
        return engine.lastError()
    }

    override fun supportsDraftSession(): Boolean {
        return engine.supportsDraftSession()
    }

    override fun supportsSplitDraftControl(): Boolean {
        return engine.supportsSplitDraftControl()
    }

    override fun supportsDraftTree(): Boolean {
        return engine.supportsDraftTree()
    }

    override suspend fun loadModel(modelPath: String): Boolean {
        engine.loadModel(modelPath)
        return when (val state = engine.state.value) {
            is InferenceEngine.State.ModelReady -> true
            is InferenceEngine.State.Error -> false
            else -> false
        }
    }

    override suspend fun setSystemPrompt(systemPrompt: String): Boolean {
        engine.setSystemPrompt(systemPrompt)
        return when (engine.state.value) {
            is InferenceEngine.State.ModelReady -> true
            is InferenceEngine.State.Error -> false
            else -> false
        }
    }

    override suspend fun generate(prompt: String, maxTokens: Int): String {
        val output = engine.generate(prompt, maxTokens).toList().joinToString(separator = "")
        return when (val state = engine.state.value) {
            is InferenceEngine.State.Error -> state.message
            else -> output
        }
    }

    override suspend fun startDraftSession(
        systemPrompt: String,
        userPrompt: String,
        predictLength: Int
    ): DraftSessionHandle {
        return engine.startDraftSession(systemPrompt, userPrompt, predictLength)
    }

    override suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        return engine.draftNextTokenIds(sessionId, maxTokens)
    }

    override suspend fun draftTreeProposal(sessionId: String, maxDepth: Int, branchFactor: Int): DraftTreeProposal {
        return engine.draftTreeProposal(sessionId, maxDepth, branchFactor)
    }

    override suspend fun renderTokenIds(tokenIds: List<Int>): String {
        return engine.renderTokenIds(tokenIds)
    }

    override suspend fun draftNextRealTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        return engine.draftNextRealTokenIds(sessionId, maxTokens)
    }

    override suspend fun syncAndDraftNextRealTokenIds(
        sessionId: String,
        authoritativeTokenIds: List<Int>,
        maxTokens: Int
    ): List<Int> {
        return engine.syncAndDraftNextRealTokenIds(sessionId, authoritativeTokenIds, maxTokens)
    }

    override suspend fun syncRealTokenDraftSession(
        sessionId: String,
        authoritativeTokenIds: List<Int>
    ): DraftSessionHandle {
        return engine.syncRealTokenDraftSession(sessionId, authoritativeTokenIds)
    }

    override suspend fun draftRealTokenTreeProposal(sessionId: String, maxDepth: Int, branchFactor: Int): DraftTreeProposal {
        return engine.draftRealTokenTreeProposal(sessionId, maxDepth, branchFactor)
    }

    override suspend fun applyVerifiedRealTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle {
        return engine.applyVerifiedRealTokens(sessionId, tokenIds)
    }

    override suspend fun applyVerifiedRealTokensAndDraftNextRealTokenIds(
        sessionId: String,
        tokenIds: List<Int>,
        maxTokens: Int
    ): List<Int> {
        return engine.applyVerifiedRealTokensAndDraftNextRealTokenIds(sessionId, tokenIds, maxTokens)
    }

    override suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle {
        return engine.applyVerifiedTokens(sessionId, tokenIds)
    }

    override suspend fun closeDraftSession(sessionId: String) {
        engine.closeDraftSession(sessionId)
    }

    override suspend fun benchmark(pp: Int, tg: Int, pl: Int, nr: Int): String {
        return engine.bench(pp, tg, pl, nr)
    }

    override fun cleanup() {
        engine.cleanUp()
    }
}
