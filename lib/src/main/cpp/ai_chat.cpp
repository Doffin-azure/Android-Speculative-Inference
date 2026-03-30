#include <jni.h>

#include <fstream>
#include <string>

#if defined(USE_REAL_LLAMA_CPP)
// Placeholder switch for the future real llama.cpp-backed implementation.
// The current file still uses stub behavior until the official sample logic is migrated.
#endif

namespace {
bool g_model_loaded = false;
std::string g_model_path;
std::string g_last_error = "No model loaded.";
std::string g_system_prompt;

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
    const std::string backend = "lib-native-stub (ai_chat.cpp landing zone for llama.cpp)";
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
        g_system_prompt.clear();
        g_last_error = "Model path is empty.";
        return JNI_FALSE;
    }

    if (!file_exists(path)) {
        g_model_loaded = false;
        g_model_path.clear();
        g_system_prompt.clear();
        g_last_error = "Model file does not exist: " + path;
        return JNI_FALSE;
    }

    g_model_loaded = true;
    g_model_path = path;
    g_system_prompt.clear();
    g_last_error.clear();
    return JNI_TRUE;
}

extern "C"
JNIEXPORT jboolean JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_setSystemPrompt(
        JNIEnv* env,
        jobject /* thiz */,
        jstring systemPrompt) {
    if (!g_model_loaded) {
        g_last_error = "Load a valid model file path first.";
        return JNI_FALSE;
    }

    const char* prompt_chars = env->GetStringUTFChars(systemPrompt, nullptr);
    g_system_prompt = prompt_chars ? prompt_chars : "";
    if (prompt_chars != nullptr) {
        env->ReleaseStringUTFChars(systemPrompt, prompt_chars);
    }

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
                         " predictLength=" + std::to_string(maxTokens) +
                         " prompt=" + input;
    if (!g_system_prompt.empty()) {
        output += " systemPrompt=" + g_system_prompt;
    }
    return env->NewStringUTF(output.c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_bench(
        JNIEnv* env,
        jobject /* thiz */,
        jint pp,
        jint tg,
        jint pl,
        jint nr) {
    if (!g_model_loaded) {
        g_last_error = "Load a valid model file path first.";
        return env->NewStringUTF("");
    }

    g_last_error.clear();
    std::string output = "[native-stub-bench] pp=" + std::to_string(pp) +
                         " tg=" + std::to_string(tg) +
                         " pl=" + std::to_string(pl) +
                         " nr=" + std::to_string(nr) +
                         " model=" + g_model_path;
    return env->NewStringUTF(output.c_str());
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_unloadModel(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    g_model_loaded = false;
    g_model_path.clear();
    g_system_prompt.clear();
    g_last_error = "No model loaded.";
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_destroy(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    g_model_loaded = false;
    g_model_path.clear();
    g_system_prompt.clear();
    g_last_error = "No model loaded.";
}
