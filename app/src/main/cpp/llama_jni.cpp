#include <jni.h>
#include <fstream>
#include <string>
#include <vector>

namespace {
bool g_model_loaded = false;
std::string g_model_path;
std::string g_last_error = "No model loaded.";

bool file_exists(const std::string& path) {
    std::ifstream file(path);
    return file.good();
}
}  // namespace

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_inference_LlamaBridge_backendLabel(
        JNIEnv* env,
        jobject /* thiz */) {
    const std::string backend = "stub-jni (ready for llama.cpp import)";
    return env->NewStringUTF(backend.c_str());
}

extern "C"
JNIEXPORT jboolean JNICALL
Java_com_example_myapplication_inference_LlamaBridge_isModelLoaded(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    return g_model_loaded ? JNI_TRUE : JNI_FALSE;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_inference_LlamaBridge_loadedModelPath(
        JNIEnv* env,
        jobject /* thiz */) {
    return env->NewStringUTF(g_model_path.c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_inference_LlamaBridge_lastError(
        JNIEnv* env,
        jobject /* thiz */) {
    return env->NewStringUTF(g_last_error.c_str());
}

extern "C"
JNIEXPORT jboolean JNICALL
Java_com_example_myapplication_inference_LlamaBridge_loadModel(
        JNIEnv* env,
        jobject /* thiz */,
        jstring modelPath) {
    const char* modelPathChars = env->GetStringUTFChars(modelPath, nullptr);
    std::string path = modelPathChars ? modelPathChars : "";
    if (modelPathChars != nullptr) {
        env->ReleaseStringUTFChars(modelPath, modelPathChars);
    }

    if (path.empty()) {
        g_model_loaded = false;
        g_model_path.clear();
        g_last_error = "Model path is empty.";
        return JNI_FALSE;
    }

    if (!file_exists(path)) {
        g_model_loaded = false;
        g_model_path.clear();
        g_last_error = "Model file does not exist: " + path;
        return JNI_FALSE;
    }

    g_model_loaded = true;
    g_model_path = path;
    g_last_error.clear();
    return g_model_loaded ? JNI_TRUE : JNI_FALSE;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_inference_LlamaBridge_generate(
        JNIEnv* env,
        jobject /* thiz */,
        jstring prompt,
        jint maxTokens) {
    if (!g_model_loaded) {
        g_last_error = "Stub backend: load a valid model file path first.";
        return env->NewStringUTF(g_last_error.c_str());
    }

    const char* promptChars = env->GetStringUTFChars(prompt, nullptr);
    std::string input = promptChars ? promptChars : "";
    if (promptChars != nullptr) {
        env->ReleaseStringUTFChars(prompt, promptChars);
    }

    if (input.empty()) {
        g_last_error = "Prompt is empty.";
        return env->NewStringUTF(g_last_error.c_str());
    }

    g_last_error.clear();
    std::string output = "[stub llama-jni] model=" + g_model_path +
                         " maxTokens=" + std::to_string(maxTokens) +
                         " prompt=" + input;
    return env->NewStringUTF(output.c_str());
}

extern "C"
JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_inference_LlamaBridge_draftTokenIds(
        JNIEnv* env,
        jobject /* thiz */,
        jstring prompt,
        jint count) {
    std::vector<jint> tokens;
    for (int i = 0; i < count; ++i) {
        tokens.push_back(i + 1);
    }

    jintArray result = env->NewIntArray((jsize)tokens.size());
    env->SetIntArrayRegion(result, 0, (jsize)tokens.size(), tokens.data());
    return result;
}
