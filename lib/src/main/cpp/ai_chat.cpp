#include <jni.h>

#include <fstream>
#include <string>
#include <vector>

#if defined(USE_REAL_LLAMA_CPP)
// Placeholder switch for the future real llama.cpp-backed implementation.
// The current file still uses stub behavior until llama.cpp sources are wired in.
#endif

namespace {
std::string g_native_lib_dir;
bool g_model_loaded = false;
std::string g_model_path;
std::string g_last_error = "No model loaded.";
std::string g_system_prompt;
std::vector<std::string> g_generated_tokens;
size_t g_generated_index = 0;

bool file_exists(const std::string& path) {
    std::ifstream file(path);
    return file.good();
}

void reset_generation() {
    g_generated_tokens.clear();
    g_generated_index = 0;
}
}  // namespace

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_init(
        JNIEnv* env,
        jobject /* thiz */,
        jstring nativeLibDir) {
    const char* native_lib_dir_chars = env->GetStringUTFChars(nativeLibDir, nullptr);
    g_native_lib_dir = native_lib_dir_chars ? native_lib_dir_chars : "";
    if (native_lib_dir_chars != nullptr) {
        env->ReleaseStringUTFChars(nativeLibDir, native_lib_dir_chars);
    }
    g_last_error.clear();
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_load(
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
        reset_generation();
        g_last_error = "Model path is empty.";
        return 1;
    }

    if (!file_exists(path)) {
        g_model_loaded = false;
        g_model_path.clear();
        g_system_prompt.clear();
        reset_generation();
        g_last_error = "Model file does not exist: " + path;
        return 2;
    }

    g_model_loaded = true;
    g_model_path = path;
    g_system_prompt.clear();
    reset_generation();
    g_last_error.clear();
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_prepare(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    if (!g_model_loaded) {
        g_last_error = "No model is loaded.";
        return 1;
    }

    g_last_error.clear();
    return 0;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_systemInfo(
        JNIEnv* env,
        jobject /* thiz */) {
    std::string info = "stub ai-chat; nativeLibDir=" + g_native_lib_dir;
    return env->NewStringUTF(info.c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_benchModel(
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
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_processSystemPrompt(
        JNIEnv* env,
        jobject /* thiz */,
        jstring systemPrompt) {
    if (!g_model_loaded) {
        g_last_error = "Load a valid model file path first.";
        return 1;
    }

    const char* prompt_chars = env->GetStringUTFChars(systemPrompt, nullptr);
    g_system_prompt = prompt_chars ? prompt_chars : "";
    if (prompt_chars != nullptr) {
        env->ReleaseStringUTFChars(systemPrompt, prompt_chars);
    }

    g_last_error.clear();
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_processUserPrompt(
        JNIEnv* env,
        jobject /* thiz */,
        jstring prompt,
        jint predictLength) {
    if (!g_model_loaded) {
        g_last_error = "Load a valid model file path first.";
        return 1;
    }

    const char* prompt_chars = env->GetStringUTFChars(prompt, nullptr);
    std::string input = prompt_chars ? prompt_chars : "";
    if (prompt_chars != nullptr) {
        env->ReleaseStringUTFChars(prompt, prompt_chars);
    }

    if (input.empty()) {
        g_last_error = "Prompt is empty.";
        return 2;
    }

    reset_generation();
    g_last_error.clear();
    g_generated_tokens.push_back("[native-stub]");
    g_generated_tokens.push_back("model=" + g_model_path);
    g_generated_tokens.push_back("predictLength=" + std::to_string(predictLength));
    g_generated_tokens.push_back("prompt=" + input);
    if (!g_system_prompt.empty()) {
        g_generated_tokens.push_back("systemPrompt=" + g_system_prompt);
    }
    return 0;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateNextToken(
        JNIEnv* env,
        jobject /* thiz */) {
    if (g_generated_index >= g_generated_tokens.size()) {
        return nullptr;
    }

    const std::string& token = g_generated_tokens[g_generated_index++];
    return env->NewStringUTF(token.c_str());
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_unload(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    g_model_loaded = false;
    g_model_path.clear();
    g_system_prompt.clear();
    reset_generation();
    g_last_error = "No model loaded.";
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_shutdown(
        JNIEnv* /* env */,
        jobject /* thiz */) {
    g_model_loaded = false;
    g_model_path.clear();
    g_system_prompt.clear();
    reset_generation();
    g_native_lib_dir.clear();
    g_last_error = "No model loaded.";
}
