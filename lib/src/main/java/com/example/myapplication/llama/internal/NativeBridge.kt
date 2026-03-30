package com.example.myapplication.llama.internal

internal object NativeBridge {
    init {
        System.loadLibrary("ai-chat-jni")
    }

    external fun backendLabel(): String
    external fun isModelLoaded(): Boolean
    external fun loadedModelPath(): String
    external fun lastError(): String
    external fun loadModel(modelPath: String): Boolean
    external fun generate(prompt: String, maxTokens: Int): String
    external fun unloadModel()
}
