package com.example.myapplication.inference

import com.example.myapplication.llama.DraftSessionHandle
import com.example.myapplication.llama.DraftTreeProposal

interface LocalLlm {
    companion object {
        const val TEST_MAX_TOKENS = 1024
    }

    fun backendLabel(): String
    fun isModelLoaded(): Boolean
    fun loadedModelPath(): String
    fun lastError(): String
    fun supportsDraftSession(): Boolean = false
    fun supportsSplitDraftControl(): Boolean = false
    fun supportsDraftTree(): Boolean = false
    suspend fun loadModel(modelPath: String): Boolean
    suspend fun setSystemPrompt(systemPrompt: String): Boolean
    suspend fun generate(prompt: String, maxTokens: Int = TEST_MAX_TOKENS): String
    suspend fun startDraftSession(systemPrompt: String, userPrompt: String, predictLength: Int = TEST_MAX_TOKENS): DraftSessionHandle {
        throw UnsupportedOperationException("Draft session is not implemented by this LocalLlm.")
    }
    suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        throw UnsupportedOperationException("Draft token generation is not implemented by this LocalLlm.")
    }
    suspend fun draftTreeProposal(sessionId: String, maxDepth: Int, branchFactor: Int): DraftTreeProposal {
        throw UnsupportedOperationException("Draft tree generation is not implemented by this LocalLlm.")
    }
    suspend fun renderTokenIds(tokenIds: List<Int>): String {
        throw UnsupportedOperationException("Token rendering is not implemented by this LocalLlm.")
    }
    suspend fun draftNextRealTokenIds(sessionId: String, maxTokens: Int): List<Int> {
        throw UnsupportedOperationException("Real-token draft generation is not implemented by this LocalLlm.")
    }
    suspend fun syncAndDraftNextRealTokenIds(sessionId: String, authoritativeTokenIds: List<Int>, maxTokens: Int): List<Int> {
        throw UnsupportedOperationException("Combined split draft synchronization/generation is not implemented by this LocalLlm.")
    }
    suspend fun syncRealTokenDraftSession(sessionId: String, authoritativeTokenIds: List<Int>): DraftSessionHandle {
        throw UnsupportedOperationException("Split draft synchronization is not implemented by this LocalLlm.")
    }
    suspend fun draftRealTokenTreeProposal(sessionId: String, maxDepth: Int, branchFactor: Int): DraftTreeProposal {
        throw UnsupportedOperationException("Real-token draft tree generation is not implemented by this LocalLlm.")
    }
    suspend fun applyVerifiedRealTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle {
        throw UnsupportedOperationException("Applying verified real tokens is not implemented by this LocalLlm.")
    }
    suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle {
        throw UnsupportedOperationException("Applying verified tokens is not implemented by this LocalLlm.")
    }
    suspend fun closeDraftSession(sessionId: String) {}
    suspend fun benchmark(pp: Int, tg: Int, pl: Int, nr: Int = 1): String
    fun cleanup()
}
