package com.example.myapplication.inference

/**
 * Legacy app-local JNI bridge retained only as a fallback reference.
 * The active local inference path is now routed through the :lib module.
 */
object LlamaBridge {
    init {
        System.loadLibrary("llama-jni")
    }

    external fun backendLabel(): String
    external fun isModelLoaded(): Boolean
    external fun loadedModelPath(): String
    external fun lastError(): String
    external fun loadModel(modelPath: String): Boolean
    external fun generate(prompt: String, maxTokens: Int): String
    external fun draftTokenIds(prompt: String, count: Int): IntArray
}
