#include <jni.h>

#include <fstream>
#include <string>

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
Java_com_example_myapplication_llama_internal_NativeBridge_backendLabel(
        JNIEnv* env,
        jobject /* thiz */) {
    const std::string backend = "lib-native-stub (JNI landing zone for llama.cpp)";
    return env->NewStringUTF(backend.c_str());
}

extern "C"
JNIEXPORT jboolean JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_isModelLoaded(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    return g_model_loaded ? JNI_TRUE : JNI_FALSE;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_loadedModelPath(
        JNIEnv* env,
        jobject /* thiz */) {
    return env->NewStringUTF(g_model_path.c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_lastError(
        JNIEnv* env,
        jobject /* thiz */) {
    return env->NewStringUTF(g_last_error.c_str());
}

extern "C"
JNIEXPORT jboolean JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_loadModel(
        JNIEnv* env,
        jobject /* thiz */,
        jstring modelPath) {
    const char* model_path_chars = env->GetStringUTFChars(modelPath, nullptr);
    std::string path = model_path_chars ? model_path_chars : "";
    if (model_path_chars != nullptr) {
        env->ReleaseStringUTFChars(modelPath, model_path_chars);
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
    return JNI_TRUE;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_generate(
        JNIEnv* env,
        jobject /* thiz */,
        jstring prompt,
        jint maxTokens) {
    if (!g_model_loaded) {
        g_last_error = "Load a valid model file path first.";
        return env->NewStringUTF("");
    }

    const char* prompt_chars = env->GetStringUTFChars(prompt, nullptr);
    std::string input = prompt_chars ? prompt_chars : "";
    if (prompt_chars != nullptr) {
        env->ReleaseStringUTFChars(prompt, prompt_chars);
    }

    if (input.empty()) {
        g_last_error = "Prompt is empty.";
        return env->NewStringUTF("");
    }

    g_last_error.clear();
    std::string output = "[native-stub] model=" + g_model_path +
                         " maxTokens=" + std::to_string(maxTokens) +
                         " prompt=" + input;
    return env->NewStringUTF(output.c_str());
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_unloadModel(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    g_model_loaded = false;
    g_model_path.clear();
    g_last_error = "No model loaded.";
}
