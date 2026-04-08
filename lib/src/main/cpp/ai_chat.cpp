#include <android/log.h>
#include <algorithm>
#include <jni.h>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <iomanip>
#include <limits>
#include <mutex>
#include <utility>
#include <sampling.h>
#include <sys/stat.h>
#include <string>
#include <unordered_map>
#include <unistd.h>

#include "chat.h"
#include "common.h"
#include "llama.h"
#include "logging.h"

template<class T>
static std::string join(const std::vector<T> &values, const std::string &delim) {
    std::ostringstream str;
    for (size_t i = 0; i < values.size(); i++) {
        str << values[i];
        if (i < values.size() - 1) {
            str << delim;
        }
    }
    return str.str();
}

constexpr int N_THREADS_MIN = 2;
constexpr int N_THREADS_MAX = 4;
constexpr int N_THREADS_HEADROOM = 2;

constexpr int DEFAULT_CONTEXT_SIZE = 8192;
constexpr int OVERFLOW_HEADROOM = 4;
constexpr int BATCH_SIZE = 512;
constexpr float DEFAULT_SAMPLER_TEMP = 0.0f;
constexpr int DEFAULT_SPECULATIVE_DRAFT_TOP_K = 10;
constexpr float DEFAULT_SPECULATIVE_DRAFT_P_MIN = 0.90f;

static llama_model *g_model;
static llama_context *g_context;
static llama_batch g_batch;
static common_chat_templates_ptr g_chat_templates;
static common_sampler *g_sampler;
static std::mutex g_log_mutex;
static std::string g_recent_native_logs;

static void clear_recent_native_logs() {
    std::lock_guard<std::mutex> lock(g_log_mutex);
    g_recent_native_logs.clear();
}

void aichat_capture_log_line(const char *text) {
    if (text == nullptr || text[0] == '\0') {
        return;
    }
    std::lock_guard<std::mutex> lock(g_log_mutex);
    g_recent_native_logs.append(text);
    constexpr size_t MAX_LOG_CHARS = 4000;
    if (g_recent_native_logs.size() > MAX_LOG_CHARS) {
        g_recent_native_logs.erase(0, g_recent_native_logs.size() - MAX_LOG_CHARS);
    }
}

static std::string recent_native_logs_snapshot() {
    std::lock_guard<std::mutex> lock(g_log_mutex);
    return g_recent_native_logs;
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_init(
        JNIEnv *env,
        jobject /* unused */,
        jstring nativeLibDir) {
    clear_recent_native_logs();
    llama_log_set(aichat_android_log_callback, nullptr);

#ifdef GGML_BACKEND_DL
    const auto *path_to_backend = env->GetStringUTFChars(nativeLibDir, 0);
    LOGi("Loading dynamic backends from %s", path_to_backend);
    ggml_backend_load_all_from_path(path_to_backend);
    env->ReleaseStringUTFChars(nativeLibDir, path_to_backend);
#else
    (void) env;
    (void) nativeLibDir;
    LOGi("Loading built-in ggml backends");
    ggml_backend_load_all();
#endif

    llama_backend_init();
    LOGi("Backend initiated; log handler set.");
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_load(
        JNIEnv *env,
        jobject,
        jstring jmodel_path) {
    clear_recent_native_logs();
    llama_model_params model_params = llama_model_default_params();

    const auto *model_path = env->GetStringUTFChars(jmodel_path, 0);
    LOGd("%s: Loading model from:\n%s\n", __func__, model_path);

    struct stat model_stat {};
    if (stat(model_path, &model_stat) != 0) {
        LOGe("%s: stat() failed for model path", __func__);
        env->ReleaseStringUTFChars(jmodel_path, model_path);
        return 1;
    }

    if (model_stat.st_size <= 0) {
        LOGe("%s: model file is empty", __func__);
        env->ReleaseStringUTFChars(jmodel_path, model_path);
        return 2;
    }

    constexpr off_t MIN_REASONABLE_GGUF_SIZE = 1024 * 1024;
    if (model_stat.st_size < MIN_REASONABLE_GGUF_SIZE) {
        LOGe("%s: model file is too small to be a valid GGUF: %lld bytes", __func__, (long long) model_stat.st_size);
        env->ReleaseStringUTFChars(jmodel_path, model_path);
        return 3;
    }

    FILE *fp = fopen(model_path, "rb");
    if (fp == nullptr) {
        LOGe("%s: fopen() failed for model path", __func__);
        env->ReleaseStringUTFChars(jmodel_path, model_path);
        return 1;
    }

    char gguf_header[4];
    const size_t header_read = fread(gguf_header, 1, sizeof(gguf_header), fp);
    uint32_t gguf_version = 0;
    const size_t version_read = fread(&gguf_version, 1, sizeof(gguf_version), fp);
    fclose(fp);
    if (header_read != sizeof(gguf_header) ||
        gguf_header[0] != 'G' ||
        gguf_header[1] != 'G' ||
        gguf_header[2] != 'U' ||
        gguf_header[3] != 'F') {
        LOGe("%s: file does not start with GGUF header", __func__);
        env->ReleaseStringUTFChars(jmodel_path, model_path);
        return 4;
    }

    LOGi(
            "%s: GGUF header verified; size=%lld bytes, version=%u",
            __func__,
            (long long) model_stat.st_size,
            version_read == sizeof(gguf_version) ? gguf_version : 0u);

    auto *model = llama_model_load_from_file(model_path, model_params);
    if (!model) {
        LOGw("%s: default load failed; retrying with use_mmap = false", __func__);
        model_params = llama_model_default_params();
        model_params.use_mmap = false;
        model = llama_model_load_from_file(model_path, model_params);
        if (model) {
            LOGi("%s: fallback load with use_mmap = false succeeded", __func__);
        }
    }
    env->ReleaseStringUTFChars(jmodel_path, model_path);
    if (!model) {
        LOGe("%s: llama_model_load_from_file() returned null after GGUF validation", __func__);
        return 5;
    }
    g_model = model;
    return 0;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_lastNativeLoadDiagnostics(
        JNIEnv *env,
        jobject /* unused */) {
    const std::string snapshot = recent_native_logs_snapshot();
    return env->NewStringUTF(snapshot.c_str());
}

static llama_context *init_context(llama_model *model, const int n_ctx = DEFAULT_CONTEXT_SIZE) {
    if (!model) {
        LOGe("%s: model cannot be null", __func__);
        return nullptr;
    }

    const int n_threads = std::max(
            N_THREADS_MIN,
            std::min(N_THREADS_MAX, (int) sysconf(_SC_NPROCESSORS_ONLN) - N_THREADS_HEADROOM));
    LOGi("%s: Using %d threads", __func__, n_threads);

    llama_context_params ctx_params = llama_context_default_params();
    const int trained_context_size = llama_model_n_ctx_train(model);
    if (n_ctx > trained_context_size) {
        LOGw(
                "%s: Model was trained with only %d context size! Enforcing %d context size...",
                __func__,
                trained_context_size,
                n_ctx);
    }
    ctx_params.n_ctx = n_ctx;
    ctx_params.n_batch = BATCH_SIZE;
    ctx_params.n_ubatch = BATCH_SIZE;
    ctx_params.n_threads = n_threads;
    ctx_params.n_threads_batch = n_threads;
    auto *context = llama_init_from_model(g_model, ctx_params);
    if (context == nullptr) {
        LOGe("%s: llama_init_from_model() returned null", __func__);
    }
    return context;
}

static common_sampler *new_sampler(float temp) {
    common_params_sampling sparams;
    sparams.temp = temp;
    sparams.top_k = 1;
    sparams.top_p = 1.0f;
    sparams.min_p = 0.0f;
    sparams.penalty_repeat = 1.0f;
    sparams.penalty_freq = 0.0f;
    sparams.penalty_present = 0.0f;
    return common_sampler_init(g_model, sparams);
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_prepare(
        JNIEnv * /* env */,
        jobject /* unused */) {
    auto *context = init_context(g_model);
    if (!context) {
        return 1;
    }
    g_context = context;
    g_batch = llama_batch_init(BATCH_SIZE, 0, 1);
    g_chat_templates = common_chat_templates_init(g_model, "");
    g_sampler = new_sampler(DEFAULT_SAMPLER_TEMP);
    return 0;
}

static std::string get_backend() {
    std::vector<std::string> backends;
    for (size_t i = 0; i < ggml_backend_reg_count(); i++) {
        auto *reg = ggml_backend_reg_get(i);
        std::string name = ggml_backend_reg_name(reg);
        if (name != "CPU") {
            backends.push_back(ggml_backend_reg_name(reg));
        }
    }
    return backends.empty() ? "CPU" : join(backends, ",");
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_systemInfo(
        JNIEnv *env,
        jobject /* unused */) {
    return env->NewStringUTF(llama_print_system_info());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_benchModel(
        JNIEnv *env,
        jobject /* unused */,
        jint pp,
        jint tg,
        jint pl,
        jint nr) {
    auto *context = init_context(g_model, pp);
    if (!context) {
        const auto *const err_msg = "Fail to init_context! Bench aborted.";
        LOGe("%s", err_msg);
        return env->NewStringUTF(err_msg);
    }

    auto pp_avg = 0.0;
    auto tg_avg = 0.0;
    auto pp_std = 0.0;
    auto tg_std = 0.0;

    const uint32_t n_ctx = llama_n_ctx(context);
    LOGi("n_ctx = %d", n_ctx);

    for (int nri = 0; nri < nr; nri++) {
        LOGi("Benchmark prompt processing (pp = %d)", pp);

        common_batch_clear(g_batch);

        const int n_tokens = pp;
        for (int i = 0; i < n_tokens; i++) {
            common_batch_add(g_batch, 0, i, {0}, false);
        }

        g_batch.logits[g_batch.n_tokens - 1] = true;
        llama_memory_clear(llama_get_memory(context), false);

        const auto t_pp_start = ggml_time_us();
        if (llama_decode(context, g_batch) != 0) {
            LOGe("llama_decode() failed during prompt processing");
        }
        const auto t_pp_end = ggml_time_us();

        LOGi("Benchmark text generation (tg = %d)", tg);

        llama_memory_clear(llama_get_memory(context), false);
        const auto t_tg_start = ggml_time_us();
        for (int i = 0; i < tg; i++) {
            common_batch_clear(g_batch);
            for (int j = 0; j < pl; j++) {
                common_batch_add(g_batch, 0, i, {j}, true);
            }

            if (llama_decode(context, g_batch) != 0) {
                LOGe("llama_decode() failed during text generation");
            }
        }
        const auto t_tg_end = ggml_time_us();

        llama_memory_clear(llama_get_memory(context), false);

        const auto t_pp = double(t_pp_end - t_pp_start) / 1000000.0;
        const auto t_tg = double(t_tg_end - t_tg_start) / 1000000.0;

        const auto speed_pp = double(pp) / t_pp;
        const auto speed_tg = double(pl * tg) / t_tg;

        pp_avg += speed_pp;
        tg_avg += speed_tg;

        pp_std += speed_pp * speed_pp;
        tg_std += speed_tg * speed_tg;

        LOGi("pp %f t/s, tg %f t/s", speed_pp, speed_tg);
    }

    llama_free(context);

    pp_avg /= double(nr);
    tg_avg /= double(nr);

    if (nr > 1) {
        pp_std = sqrt(pp_std / double(nr - 1) - pp_avg * pp_avg * double(nr) / double(nr - 1));
        tg_std = sqrt(tg_std / double(nr - 1) - tg_avg * tg_avg * double(nr) / double(nr - 1));
    } else {
        pp_std = 0;
        tg_std = 0;
    }

    char model_desc[128];
    llama_model_desc(g_model, model_desc, sizeof(model_desc));

    const auto model_size = double(llama_model_size(g_model)) / 1024.0 / 1024.0 / 1024.0;
    const auto model_n_params = double(llama_model_n_params(g_model)) / 1e9;

    const auto backend = get_backend();
    std::stringstream result;
    result << std::setprecision(3);
    result << "| model | size | params | backend | test | t/s |\n";
    result << "| --- | --- | --- | --- | --- | --- |\n";
    result << "| " << model_desc << " | " << model_size << "GiB | " << model_n_params << "B | "
           << backend << " | pp " << pp << " | " << pp_avg << " +/- " << pp_std << " |\n";
    result << "| " << model_desc << " | " << model_size << "GiB | " << model_n_params << "B | "
           << backend << " | tg " << tg << " | " << tg_avg << " +/- " << tg_std << " |\n";
    return env->NewStringUTF(result.str().c_str());
}

constexpr const char *ROLE_SYSTEM = "system";
constexpr const char *ROLE_USER = "user";
constexpr const char *ROLE_ASSISTANT = "assistant";

static std::vector<common_chat_msg> chat_msgs;
static llama_pos system_prompt_position;
static llama_pos current_position;
static std::vector<llama_token> runtime_token_history;

static void reset_long_term_states(const bool clear_kv_cache = true) {
    chat_msgs.clear();
    system_prompt_position = 0;
    current_position = 0;
    runtime_token_history.clear();

    if (clear_kv_cache) {
        llama_memory_clear(llama_get_memory(g_context), false);
    }
}

static void shift_context() {
    const int n_discard = (current_position - system_prompt_position) / 2;
    LOGi("%s: Discarding %d tokens", __func__, n_discard);
    llama_memory_seq_rm(
            llama_get_memory(g_context),
            0,
            system_prompt_position,
            system_prompt_position + n_discard);
    llama_memory_seq_add(
            llama_get_memory(g_context),
            0,
            system_prompt_position + n_discard,
            current_position,
            -n_discard);
    current_position -= n_discard;
    LOGi("%s: Context shifting done! Current position: %d", __func__, current_position);
}

static std::string chat_add_and_format(const std::string &role, const std::string &content) {
    common_chat_msg new_msg;
    new_msg.role = role;
    new_msg.content = content;
    auto formatted = common_chat_format_single(
            g_chat_templates.get(),
            chat_msgs,
            new_msg,
            role == ROLE_USER,
            false);
    chat_msgs.push_back(new_msg);
    LOGi("%s: Formatted and added %s message:\n%s\n", __func__, role.c_str(), formatted.c_str());
    return formatted;
}

static llama_pos stop_generation_position;
static std::string cached_token_chars;
static std::ostringstream assistant_ss;

static void reset_short_term_states() {
    stop_generation_position = 0;
    cached_token_chars.clear();
    assistant_ss.str("");
}

static int decode_tokens_in_batches(
        llama_context *context,
        llama_batch &batch,
        const llama_tokens &tokens,
        const llama_pos start_pos,
        const bool compute_last_logit);
static bool rebuild_runtime_to_token_sequence(
        const struct persistent_draft_session_snapshot &session_snapshot,
        const std::vector<llama_token> &target_sequence,
        int predict_length);

static bool is_valid_utf8(const char *string);
static void rebuild_sampler_history_from_runtime_tokens();

struct draft_tree_candidate {
    llama_token token_id;
    std::string token_text;
    float probability;
    float log_probability;
};

struct host_runtime_probe_snapshot {
    llama_pos system_prompt_position;
    llama_pos current_position;
    llama_pos stop_generation_position;
    std::string cached_token_chars;
    std::string assistant_text;
    std::vector<llama_token> runtime_token_history;
};

struct runtime_branch_snapshot {
    std::vector<uint8_t> state_data;
    host_runtime_probe_snapshot host_snapshot;
};

struct persistent_draft_session_snapshot {
    std::vector<uint8_t> seq_state_data;
    bool seq_state_valid;
    host_runtime_probe_snapshot host_snapshot;
    std::vector<llama_token> prompt_prefix_tokens;
};

static std::unordered_map<std::string, persistent_draft_session_snapshot> g_persistent_draft_sessions;
static std::string g_active_persistent_draft_session_id;
static bool g_active_runtime_matches_committed_snapshot = false;

struct draft_tree_branch {
    runtime_branch_snapshot snapshot;
    int parent_node_index;
    int depth;
    float cumulative_log_probability;
    std::string path_text;
    std::vector<int> path_ids;
    std::vector<int> path_node_indices;
};

struct draft_path_step_candidate {
    int node_index;
    llama_token token_id;
    std::string token_text;
    float probability;
    float log_probability;
};

struct draft_path_step_record {
    int depth;
    int parent_node_index;
    std::vector<int> accepted_prefix_token_ids;
    std::vector<draft_path_step_candidate> candidates;
    int best_token_id;
    int best_node_index;
};

static std::string detokenize_token_ids(const std::vector<int> &token_ids, const bool special = true) {
    if (g_context == nullptr || token_ids.empty()) {
        return "";
    }

    std::vector<llama_token> tokens;
    tokens.reserve(token_ids.size());
    for (const int token_id : token_ids) {
        if (token_id >= 0) {
            tokens.push_back(static_cast<llama_token>(token_id));
        }
    }
    if (tokens.empty()) {
        return "";
    }
    return common_detokenize(g_context, tokens, special);
}

static void append_runtime_tokens(const llama_tokens &tokens) {
    runtime_token_history.insert(runtime_token_history.end(), tokens.begin(), tokens.end());
}

static host_runtime_probe_snapshot capture_host_runtime_snapshot() {
    return {
            system_prompt_position,
            current_position,
            stop_generation_position,
            cached_token_chars,
            assistant_ss.str(),
            runtime_token_history
    };
}

static std::string json_escape(const std::string &input) {
    std::ostringstream out;
    for (const unsigned char ch: input) {
        switch (ch) {
            case '\\':
                out << "\\\\";
                break;
            case '"':
                out << "\\\"";
                break;
            case '\b':
                out << "\\b";
                break;
            case '\f':
                out << "\\f";
                break;
            case '\n':
                out << "\\n";
                break;
            case '\r':
                out << "\\r";
                break;
            case '\t':
                out << "\\t";
                break;
            default:
                if (ch < 0x20) {
                    out << "\\u"
                        << std::hex
                        << std::setw(4)
                        << std::setfill('0')
                        << static_cast<int>(ch)
                        << std::dec;
                } else {
                    out << static_cast<char>(ch);
                }
                break;
        }
    }
    return out.str();
}

static void append_json_int_array(std::ostringstream &out, const std::vector<int> &values) {
    out << "[";
    for (size_t i = 0; i < values.size(); ++i) {
        if (i > 0) {
            out << ",";
        }
        out << values[i];
    }
    out << "]";
}

static void append_json_draft_path_steps(
        std::ostringstream &out,
        const std::vector<draft_path_step_record> &steps) {
    out << "[";
    for (size_t step_index = 0; step_index < steps.size(); ++step_index) {
        if (step_index > 0) {
            out << ",";
        }
        const auto &step = steps[step_index];
        out << "{"
            << "\"depth\":" << step.depth << ","
            << "\"parentNodeIndex\":" << step.parent_node_index << ","
            << "\"acceptedPrefixTokenIds\":";
        append_json_int_array(out, step.accepted_prefix_token_ids);
        out << ",\"bestTokenId\":" << step.best_token_id
            << ",\"bestNodeIndex\":" << step.best_node_index
            << ",\"candidates\":[";
        for (size_t candidate_index = 0; candidate_index < step.candidates.size(); ++candidate_index) {
            if (candidate_index > 0) {
                out << ",";
            }
            const auto &candidate = step.candidates[candidate_index];
            out << "{"
                << "\"nodeIndex\":" << candidate.node_index << ","
                << "\"tokenId\":" << static_cast<int>(candidate.token_id) << ","
                << "\"tokenText\":\"" << json_escape(candidate.token_text) << "\","
                << "\"probability\":" << candidate.probability << ","
                << "\"logProbability\":" << candidate.log_probability
                << "}";
        }
        out << "]}";
    }
    out << "]";
}

static void append_utf8_codepoints(const std::string &emitted, std::vector<int> &out_ids) {
    for (size_t i = 0; i < emitted.size();) {
        uint32_t codepoint = 0;
        const unsigned char lead = static_cast<unsigned char>(emitted[i]);
        int length = 1;
        if ((lead & 0x80u) == 0) {
            codepoint = lead;
        } else if ((lead & 0xE0u) == 0xC0u && i + 1 < emitted.size()) {
            codepoint = ((lead & 0x1Fu) << 6) |
                        (static_cast<unsigned char>(emitted[i + 1]) & 0x3Fu);
            length = 2;
        } else if ((lead & 0xF0u) == 0xE0u && i + 2 < emitted.size()) {
            codepoint = ((lead & 0x0Fu) << 12) |
                        ((static_cast<unsigned char>(emitted[i + 1]) & 0x3Fu) << 6) |
                        (static_cast<unsigned char>(emitted[i + 2]) & 0x3Fu);
            length = 3;
        } else if ((lead & 0xF8u) == 0xF0u && i + 3 < emitted.size()) {
            codepoint = ((lead & 0x07u) << 18) |
                        ((static_cast<unsigned char>(emitted[i + 1]) & 0x3Fu) << 12) |
                        ((static_cast<unsigned char>(emitted[i + 2]) & 0x3Fu) << 6) |
                        (static_cast<unsigned char>(emitted[i + 3]) & 0x3Fu);
            length = 4;
        } else {
            codepoint = lead;
        }
        out_ids.push_back((int) codepoint);
        i += length;
    }
}

static jint first_codepoint_id_from_text(const std::string &text) {
    std::vector<int> codepoints;
    append_utf8_codepoints(text, codepoints);
    return codepoints.empty() ? -1 : codepoints.front();
}

static std::vector<draft_tree_candidate> top_candidates_from_current_logits(int branch_factor) {
    std::vector<draft_tree_candidate> candidates;
    if (branch_factor <= 0) {
        return candidates;
    }

    const float *logits = llama_get_logits(g_context);
    if (logits == nullptr) {
        return candidates;
    }

    const int vocab_size = static_cast<int>(llama_vocab_n_tokens(llama_model_get_vocab(g_model)));
    if (vocab_size <= 0) {
        return candidates;
    }

    std::vector<int> token_indices(vocab_size);
    for (int token_id = 0; token_id < vocab_size; ++token_id) {
        token_indices[token_id] = token_id;
    }

    const int keep = std::min(branch_factor, vocab_size);
    std::partial_sort(
            token_indices.begin(),
            token_indices.begin() + keep,
            token_indices.end(),
            [&](const int lhs, const int rhs) {
                return logits[lhs] > logits[rhs];
            });

    float max_logit = -std::numeric_limits<float>::infinity();
    for (int token_id = 0; token_id < vocab_size; ++token_id) {
        max_logit = std::max(max_logit, logits[token_id]);
    }

    double sum_exp = 0.0;
    for (int token_id = 0; token_id < vocab_size; ++token_id) {
        sum_exp += std::exp(static_cast<double>(logits[token_id] - max_logit));
    }
    const double log_denom = std::log(sum_exp) + static_cast<double>(max_logit);

    candidates.reserve(keep);
    for (int i = 0; i < keep; ++i) {
        const llama_token token_id = token_indices[i];
        const float log_probability = logits[token_id] - static_cast<float>(log_denom);
        const float probability = std::exp(log_probability);
        candidates.push_back({
                                     token_id,
                                     common_token_to_piece(g_context, token_id),
                                     probability,
                                     log_probability,
                             });
    }

    return candidates;
}

static bool next_real_draft_candidate(llama_token &out_token_id, std::string &out_token_text, float &out_probability) {
    out_token_id = common_sampler_sample(g_sampler, g_context, -1, true);
    if (out_token_id == LLAMA_TOKEN_NULL) {
        return false;
    }

    out_token_text = common_token_to_piece(g_context, out_token_id);
    out_probability = 1.0f;

    auto * candidates = common_sampler_get_candidates(g_sampler, true);
    if (candidates != nullptr && candidates->size > 0) {
        for (size_t index = 0; index < candidates->size; ++index) {
            const auto &candidate = candidates->data[index];
            if (candidate.id == out_token_id) {
                out_probability = candidate.p;
                break;
            }
        }
    }

    return true;
}

static std::string top_candidates_to_json(const std::vector<draft_tree_candidate> &candidates) {
    std::ostringstream out;
    out << "[";
    for (size_t i = 0; i < candidates.size(); ++i) {
        if (i > 0) {
            out << ",";
        }
        const auto &candidate = candidates[i];
        out << "{"
            << "\"tokenId\":" << static_cast<int>(candidate.token_id) << ","
            << "\"tokenText\":\"" << json_escape(candidate.token_text) << "\","
            << "\"probability\":" << candidate.probability << ","
            << "\"logProbability\":" << candidate.log_probability
            << "}";
    }
    out << "]";
    return out.str();
}

static bool candidate_vectors_equivalent(
        const std::vector<draft_tree_candidate> &lhs,
        const std::vector<draft_tree_candidate> &rhs,
        const float tolerance = 1e-5f) {
    if (lhs.size() != rhs.size()) {
        return false;
    }

    for (size_t i = 0; i < lhs.size(); ++i) {
        if (lhs[i].token_text != rhs[i].token_text) {
            return false;
        }
        if (std::fabs(lhs[i].probability - rhs[i].probability) > tolerance) {
            return false;
        }
    }
    return true;
}

static std::pair<llama_token, std::string> sample_one_token_for_probe() {
    if (current_position >= DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM) {
        shift_context();
    }

    if (current_position >= stop_generation_position) {
        return {LLAMA_TOKEN_NULL, ""};
    }

    const auto new_token_id = common_sampler_sample(g_sampler, g_context, -1);
    common_sampler_accept(g_sampler, new_token_id, true);

    common_batch_clear(g_batch);
    common_batch_add(g_batch, new_token_id, current_position, {0}, true);
    if (llama_decode(g_context, g_batch) != 0) {
        LOGe("%s: llama_decode() failed for probe token", __func__);
        return {LLAMA_TOKEN_NULL, ""};
    }

    current_position++;
    runtime_token_history.push_back(new_token_id);
    auto token_text = common_token_to_piece(g_context, new_token_id);
    cached_token_chars += token_text;
    if (is_valid_utf8(cached_token_chars.c_str())) {
        assistant_ss << cached_token_chars;
        cached_token_chars.clear();
    }
    return {new_token_id, token_text};
}

static bool rebuild_logits_cursor_from_snapshot(const host_runtime_probe_snapshot &snapshot) {
    if (snapshot.runtime_token_history.empty() || snapshot.current_position <= 0) {
        return true;
    }

    const llama_pos last_token_position = snapshot.current_position - 1;
    const llama_token last_token = snapshot.runtime_token_history.back();
    if (!llama_memory_seq_rm(
            llama_get_memory(g_context),
            0,
            last_token_position,
            snapshot.current_position)) {
        LOGw("%s: failed to remove last token position before replay", __func__);
    }

    common_batch_clear(g_batch);
    common_batch_add(g_batch, last_token, last_token_position, {0}, true);
    if (llama_decode(g_context, g_batch) != 0) {
        LOGe("%s: failed to replay last token after restore", __func__);
        return false;
    }

    return true;
}

static runtime_branch_snapshot capture_runtime_branch_snapshot() {
    const size_t state_size = llama_state_get_size(g_context);
    runtime_branch_snapshot snapshot {
            std::vector<uint8_t>(state_size),
            capture_host_runtime_snapshot()
    };
    const size_t saved_size = llama_state_get_data(g_context, snapshot.state_data.data(), snapshot.state_data.size());
    snapshot.state_data.resize(saved_size);
    return snapshot;
}

static bool restore_runtime_branch_snapshot(const runtime_branch_snapshot &snapshot) {
    if (llama_state_set_data(g_context, snapshot.state_data.data(), snapshot.state_data.size()) != snapshot.state_data.size()) {
        LOGe("%s: failed to restore runtime branch state", __func__);
        return false;
    }

    system_prompt_position = snapshot.host_snapshot.system_prompt_position;
    current_position = snapshot.host_snapshot.current_position;
    stop_generation_position = snapshot.host_snapshot.stop_generation_position;
    cached_token_chars = snapshot.host_snapshot.cached_token_chars;
    assistant_ss.str("");
    assistant_ss.clear();
    assistant_ss << snapshot.host_snapshot.assistant_text;
    runtime_token_history = snapshot.host_snapshot.runtime_token_history;
    return rebuild_logits_cursor_from_snapshot(snapshot.host_snapshot);
}

static persistent_draft_session_snapshot capture_persistent_draft_session_snapshot(
        const std::vector<llama_token> &prompt_prefix_tokens = {}) {
    constexpr llama_seq_id seq_id = 0;
    const size_t seq_state_size = llama_state_seq_get_size(g_context, seq_id);
    persistent_draft_session_snapshot snapshot {
            std::vector<uint8_t>(seq_state_size),
            true,
            capture_host_runtime_snapshot(),
            prompt_prefix_tokens
    };
    const size_t saved_size = llama_state_seq_get_data(
            g_context,
            snapshot.seq_state_data.data(),
            snapshot.seq_state_data.size(),
            seq_id);
    snapshot.seq_state_data.resize(saved_size);
    return snapshot;
}

static std::vector<llama_token> capture_prompt_prefix_tokens_from_runtime() {
    return runtime_token_history;
}

static bool restore_persistent_draft_session_snapshot(const persistent_draft_session_snapshot &snapshot) {
    if (!snapshot.seq_state_valid) {
        return false;
    }
    constexpr llama_seq_id seq_id = 0;
    llama_memory_seq_rm(llama_get_memory(g_context), seq_id, -1, -1);
    if (llama_state_seq_set_data(
            g_context,
            snapshot.seq_state_data.data(),
            snapshot.seq_state_data.size(),
            seq_id) != snapshot.seq_state_data.size()) {
        LOGe("%s: failed to restore draft session sequence state", __func__);
        return false;
    }

    system_prompt_position = snapshot.host_snapshot.system_prompt_position;
    current_position = snapshot.host_snapshot.current_position;
    stop_generation_position = snapshot.host_snapshot.stop_generation_position;
    cached_token_chars = snapshot.host_snapshot.cached_token_chars;
    assistant_ss.str("");
    assistant_ss.clear();
    assistant_ss << snapshot.host_snapshot.assistant_text;
    runtime_token_history = snapshot.host_snapshot.runtime_token_history;
    if (!rebuild_logits_cursor_from_snapshot(snapshot.host_snapshot)) {
        return false;
    }
    rebuild_sampler_history_from_runtime_tokens();
    return true;
}

static bool rollback_active_runtime_to_committed_snapshot(const persistent_draft_session_snapshot &snapshot) {
    const auto &host_snapshot = snapshot.host_snapshot;
    if (current_position < host_snapshot.current_position) {
        return false;
    }
    if (runtime_token_history.size() < host_snapshot.runtime_token_history.size()) {
        return false;
    }
    if (!std::equal(
                host_snapshot.runtime_token_history.begin(),
                host_snapshot.runtime_token_history.end(),
                runtime_token_history.begin())) {
        return false;
    }

    if (current_position > host_snapshot.current_position) {
        if (!llama_memory_seq_rm(
                    llama_get_memory(g_context),
                    0,
                    host_snapshot.current_position,
                    current_position)) {
            return false;
        }
    }

    system_prompt_position = host_snapshot.system_prompt_position;
    current_position = host_snapshot.current_position;
    stop_generation_position = host_snapshot.stop_generation_position;
    cached_token_chars = host_snapshot.cached_token_chars;
    assistant_ss.str("");
    assistant_ss.clear();
    assistant_ss << host_snapshot.assistant_text;
    runtime_token_history = host_snapshot.runtime_token_history;
    if (!rebuild_logits_cursor_from_snapshot(host_snapshot)) {
        return false;
    }
    rebuild_sampler_history_from_runtime_tokens();
    return true;
}

static size_t token_lcp_length(
        const std::vector<llama_token> &lhs,
        const std::vector<llama_token> &rhs) {
    const size_t limit = std::min(lhs.size(), rhs.size());
    size_t index = 0;
    while (index < limit && lhs[index] == rhs[index]) {
        ++index;
    }
    return index;
}

static void rebuild_sampler_history_from_runtime_tokens() {
    if (g_sampler == nullptr) {
        return;
    }
    common_sampler_reset(g_sampler);
    for (const llama_token token_id : runtime_token_history) {
        common_sampler_accept(g_sampler, token_id, false);
    }
}

static bool refresh_runtime_tail_logits() {
    if (runtime_token_history.empty() || current_position <= 0) {
        return true;
    }

    const llama_pos tail_position = current_position - 1;
    const llama_token tail_token = runtime_token_history.back();
    if (!llama_memory_seq_rm(
            llama_get_memory(g_context),
            0,
            tail_position,
            current_position)) {
        LOGw("%s: failed to remove tail token before refresh", __func__);
    }

    common_batch_clear(g_batch);
    common_batch_add(g_batch, tail_token, tail_position, {0}, true);
    if (llama_decode(g_context, g_batch) != 0) {
        LOGe("%s: failed to refresh tail logits", __func__);
        return false;
    }
    return true;
}

static bool rebuild_runtime_to_token_sequence(
        const persistent_draft_session_snapshot &session_snapshot,
        const std::vector<llama_token> &target_sequence,
        const int predict_length) {
    reset_long_term_states();
    reset_short_term_states();
    if (g_sampler != nullptr) {
        common_sampler_reset(g_sampler);
    }
    if (!target_sequence.empty() &&
        decode_tokens_in_batches(g_context, g_batch, target_sequence, 0, true) != 0) {
        LOGe("%s: failed to rebuild runtime from token sequence", __func__);
        return false;
    }

    append_runtime_tokens(target_sequence);
    current_position = static_cast<llama_pos>(target_sequence.size());
    system_prompt_position = session_snapshot.host_snapshot.system_prompt_position;
    stop_generation_position = current_position + std::max(1, predict_length);
    cached_token_chars.clear();
    assistant_ss.str("");
    assistant_ss.clear();
    // Keep split draft sync token-first on the hot path.
    // Reconstructing full assistant text here is O(prefix) and not needed for real-token draft proposal.
    rebuild_sampler_history_from_runtime_tokens();
    return true;
}

static bool sync_runtime_to_authoritative_tokens(
        const persistent_draft_session_snapshot &session_snapshot,
        const std::vector<llama_token> &authoritative_token_ids,
        const int predict_length) {
    std::vector<llama_token> target_sequence = session_snapshot.prompt_prefix_tokens;
    target_sequence.insert(
            target_sequence.end(),
            authoritative_token_ids.begin(),
            authoritative_token_ids.end());

    const size_t common_prefix = token_lcp_length(runtime_token_history, target_sequence);
    const bool mismatch_inside_prefix = common_prefix < std::min(runtime_token_history.size(), target_sequence.size());

    if (mismatch_inside_prefix) {
        return rebuild_runtime_to_token_sequence(session_snapshot, target_sequence, predict_length);
    }

    if (runtime_token_history.size() > target_sequence.size()) {
        if (!llama_memory_seq_rm(
                llama_get_memory(g_context),
                0,
                static_cast<llama_pos>(target_sequence.size()),
                current_position)) {
            return false;
        }
        runtime_token_history.resize(target_sequence.size());
        current_position = static_cast<llama_pos>(target_sequence.size());
    }

    if (runtime_token_history.size() < target_sequence.size()) {
        llama_tokens missing_tokens(
                target_sequence.begin() + static_cast<long>(runtime_token_history.size()),
                target_sequence.end());
        if (decode_tokens_in_batches(g_context, g_batch, missing_tokens, current_position, true) != 0) {
            LOGe("%s: failed to append authoritative tail", __func__);
            return false;
        }
        append_runtime_tokens(missing_tokens);
        current_position += static_cast<llama_pos>(missing_tokens.size());
    } else if (!refresh_runtime_tail_logits()) {
        return false;
    }

    system_prompt_position = session_snapshot.host_snapshot.system_prompt_position;
    stop_generation_position = current_position + std::max(1, predict_length);
    cached_token_chars.clear();
    assistant_ss.str("");
    assistant_ss.clear();
    // Keep split draft sync token-first on the hot path.
    // Reconstructing full assistant text here is O(prefix) and not needed for real-token draft proposal.
    rebuild_sampler_history_from_runtime_tokens();
    return true;
}

static void clear_active_persistent_draft_runtime();
static void mark_active_persistent_draft_runtime(
        const std::string &session_id,
        const bool matches_committed_snapshot);

static bool ensure_runtime_ready_for_authoritative_sync(
        const std::string &session_id,
        const persistent_draft_session_snapshot &snapshot) {
    if (session_id == g_active_persistent_draft_session_id) {
        return true;
    }

    if (!snapshot.seq_state_valid) {
        const int predict_length = std::max(
                1,
                static_cast<int>(snapshot.host_snapshot.stop_generation_position - snapshot.host_snapshot.current_position));
        if (rebuild_runtime_to_token_sequence(
                snapshot,
                snapshot.host_snapshot.runtime_token_history,
                predict_length)) {
            mark_active_persistent_draft_runtime(session_id, true);
            return true;
        }
    }

    if (restore_persistent_draft_session_snapshot(snapshot)) {
        mark_active_persistent_draft_runtime(session_id, true);
        return true;
    }

    clear_active_persistent_draft_runtime();
    return false;
}

static std::vector<jint> generate_real_draft_token_ids(const jint max_tokens) {
    std::vector<jint> draft_ids;
    draft_ids.reserve(std::max(0, static_cast<int>(max_tokens)));
    bool drafted_any = false;

    for (int step = 0; step < max_tokens; ++step) {
        if (current_position >= DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM) {
            shift_context();
        }

        if (current_position >= stop_generation_position) {
            break;
        }

        llama_token new_token_id = LLAMA_TOKEN_NULL;
        std::string new_token_chars;
        float new_token_probability = 0.0f;
        if (!next_real_draft_candidate(new_token_id, new_token_chars, new_token_probability)) {
            break;
        }
        common_sampler_accept(g_sampler, new_token_id, true);

        common_batch_clear(g_batch);
        common_batch_add(g_batch, new_token_id, current_position, {0}, true);
        if (llama_decode(g_context, g_batch) != 0) {
            LOGe("%s: llama_decode() failed for real draft token", __func__);
            break;
        }

        current_position++;

        if (llama_vocab_is_eog(llama_model_get_vocab(g_model), new_token_id)) {
            chat_add_and_format(ROLE_ASSISTANT, assistant_ss.str());
            break;
        }

        cached_token_chars += new_token_chars;
        if (is_valid_utf8(cached_token_chars.c_str())) {
            assistant_ss << cached_token_chars;
            cached_token_chars.clear();
        }

        draft_ids.push_back(static_cast<jint>(new_token_id));
        drafted_any = true;

        if (new_token_probability < DEFAULT_SPECULATIVE_DRAFT_P_MIN) {
            break;
        }
    }

    if (!g_active_persistent_draft_session_id.empty() && drafted_any) {
        g_active_runtime_matches_committed_snapshot = false;
    }

    return draft_ids;
}

static void clear_active_persistent_draft_runtime() {
    g_active_persistent_draft_session_id.clear();
    g_active_runtime_matches_committed_snapshot = false;
}

static void mark_active_persistent_draft_runtime(
        const std::string &session_id,
        const bool matches_committed_snapshot) {
    g_active_persistent_draft_session_id = session_id;
    g_active_runtime_matches_committed_snapshot = matches_committed_snapshot;
}

static bool advance_runtime_with_token(const llama_token token_id, const std::string &token_text) {
    if (current_position >= DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM) {
        shift_context();
    }

    if (current_position >= stop_generation_position) {
        return false;
    }

    common_batch_clear(g_batch);
    common_batch_add(g_batch, token_id, current_position, {0}, true);
    if (llama_decode(g_context, g_batch) != 0) {
        LOGe("%s: llama_decode() failed for explicit token", __func__);
        return false;
    }

    current_position++;
    runtime_token_history.push_back(token_id);
    cached_token_chars += token_text;
    if (is_valid_utf8(cached_token_chars.c_str())) {
        assistant_ss << cached_token_chars;
        cached_token_chars.clear();
    }

    return true;
}

static int process_prompt_text(
        const std::string &text,
        const std::string &role,
        const bool update_system_position,
        const bool compute_last_logit = false) {
    if (text.empty()) {
        return 0;
    }

    std::string formatted_prompt(text);
    const bool has_chat_template = common_chat_templates_was_explicit(g_chat_templates.get());
    if (has_chat_template) {
        formatted_prompt = chat_add_and_format(role, text);
    }

    auto tokens = common_tokenize(
            g_context,
            formatted_prompt,
            has_chat_template,
            has_chat_template);

    const int token_count = (int) tokens.size();
    const int max_batch_size = DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM;
    if (token_count > max_batch_size) {
        LOGe("%s: %s text too long for context! %d tokens, max: %d",
             __func__,
             role.c_str(),
             token_count,
             max_batch_size);
        return 1;
    }

    if (decode_tokens_in_batches(g_context, g_batch, tokens, current_position, compute_last_logit)) {
        LOGe("%s: llama_decode() failed for role=%s", __func__, role.c_str());
        return 2;
    }

    append_runtime_tokens(tokens);
    current_position += token_count;
    if (update_system_position) {
        system_prompt_position = current_position;
    }
    return 0;
}

static int process_assistant_prefill_text(const std::string &text) {
    if (text.empty()) {
        return 0;
    }

    auto tokens = common_tokenize(
            g_context,
            text,
            false,
            true);

    const int token_count = (int) tokens.size();
    const int max_batch_size = DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM;
    if (token_count > max_batch_size) {
        LOGe("%s: assistant prefill too long for context! %d tokens, max: %d",
             __func__,
             token_count,
             max_batch_size);
        return 1;
    }

    if (decode_tokens_in_batches(g_context, g_batch, tokens, current_position, true)) {
        LOGe("%s: llama_decode() failed for assistant prefill", __func__);
        return 2;
    }

    append_runtime_tokens(tokens);
    current_position += token_count;
    cached_token_chars.clear();
    assistant_ss.str("");
    assistant_ss.clear();
    assistant_ss << text;
    return 0;
}

static int reset_draft_context_internal(
        const std::string &system,
        const std::string &user,
        const std::string &assistant,
        const int predict_length) {
    clear_active_persistent_draft_runtime();
    reset_long_term_states();
    reset_short_term_states();
    if (g_sampler != nullptr) {
        common_sampler_reset(g_sampler);
    }

    const int system_result = process_prompt_text(system, ROLE_SYSTEM, true);
    if (system_result != 0) {
        return 10 + system_result;
    }

    const int user_result = process_prompt_text(user, ROLE_USER, false, true);
    if (user_result != 0) {
        return 20 + user_result;
    }

    const int assistant_result = process_assistant_prefill_text(assistant);
    if (assistant_result != 0) {
        return 30 + assistant_result;
    }

    stop_generation_position = current_position + std::max(1, predict_length);
    return 0;
}

static int decode_tokens_in_batches(
        llama_context *context,
        llama_batch &batch,
        const llama_tokens &tokens,
        const llama_pos start_pos,
        const bool compute_last_logit = false) {
    LOGd("%s: Decode %d tokens starting at position %d", __func__, (int) tokens.size(), start_pos);
    for (int i = 0; i < (int) tokens.size(); i += BATCH_SIZE) {
        const int cur_batch_size = std::min((int) tokens.size() - i, BATCH_SIZE);
        common_batch_clear(batch);
        LOGv("%s: Preparing a batch size of %d starting at: %d", __func__, cur_batch_size, i);

        if (start_pos + i + cur_batch_size >= DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM) {
            LOGw("%s: Current batch won't fit into context! Shifting...", __func__);
            shift_context();
        }

        for (int j = 0; j < cur_batch_size; j++) {
            const llama_token token_id = tokens[i + j];
            const llama_pos position = start_pos + i + j;
            const bool want_logit = compute_last_logit && (i + j == tokens.size() - 1);
            common_batch_add(batch, token_id, position, {0}, want_logit);
        }

        const int decode_result = llama_decode(context, batch);
        if (decode_result) {
            LOGe("%s: llama_decode failed w/ %d", __func__, decode_result);
            return 1;
        }
    }
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_processSystemPrompt(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsystem_prompt) {
    reset_long_term_states();
    reset_short_term_states();

    const auto *system_prompt = env->GetStringUTFChars(jsystem_prompt, nullptr);
    LOGd("%s: System prompt received:\n%s", __func__, system_prompt);
    std::string formatted_system_prompt(system_prompt);

    const bool has_chat_template = common_chat_templates_was_explicit(g_chat_templates.get());
    if (has_chat_template) {
        formatted_system_prompt = chat_add_and_format(ROLE_SYSTEM, system_prompt);
    }
    env->ReleaseStringUTFChars(jsystem_prompt, system_prompt);

    const auto system_tokens = common_tokenize(
            g_context,
            formatted_system_prompt,
            has_chat_template,
            has_chat_template);
    for (auto id : system_tokens) {
        LOGv("token: `%s`\t -> `%d`", common_token_to_piece(g_context, id).c_str(), id);
    }

    const int max_batch_size = DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM;
    if ((int) system_tokens.size() > max_batch_size) {
        LOGe(
                "%s: System prompt too long for context! %d tokens, max: %d",
                __func__,
                (int) system_tokens.size(),
                max_batch_size);
        return 1;
    }

    if (decode_tokens_in_batches(g_context, g_batch, system_tokens, current_position)) {
        LOGe("%s: llama_decode() failed!", __func__);
        return 2;
    }

    system_prompt_position = current_position = (int) system_tokens.size();
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_processUserPrompt(
        JNIEnv *env,
        jobject /* unused */,
        jstring juser_prompt,
        jint n_predict) {
    reset_short_term_states();

    const auto *const user_prompt = env->GetStringUTFChars(juser_prompt, nullptr);
    LOGd("%s: User prompt received:\n%s", __func__, user_prompt);
    std::string formatted_user_prompt(user_prompt);

    const bool has_chat_template = common_chat_templates_was_explicit(g_chat_templates.get());
    if (has_chat_template) {
        formatted_user_prompt = chat_add_and_format(ROLE_USER, user_prompt);
    }
    env->ReleaseStringUTFChars(juser_prompt, user_prompt);

    auto user_tokens = common_tokenize(
            g_context,
            formatted_user_prompt,
            has_chat_template,
            has_chat_template);
    for (auto id : user_tokens) {
        LOGv("token: `%s`\t -> `%d`", common_token_to_piece(g_context, id).c_str(), id);
    }

    const int user_prompt_size = (int) user_tokens.size();
    const int max_batch_size = DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM;
    if (user_prompt_size > max_batch_size) {
        const int skipped_tokens = user_prompt_size - max_batch_size;
        user_tokens.resize(max_batch_size);
        LOGw("%s: User prompt too long! Skipped %d tokens!", __func__, skipped_tokens);
    }

    if (decode_tokens_in_batches(g_context, g_batch, user_tokens, current_position, true)) {
        LOGe("%s: llama_decode() failed!", __func__);
        return 2;
    }

    current_position += user_prompt_size;
    stop_generation_position = current_position + user_prompt_size + n_predict;
    return 0;
}

static bool is_valid_utf8(const char *string) {
    if (!string) {
        return true;
    }

    const auto *bytes = (const unsigned char *) string;
    int num;

    while (*bytes != 0x00) {
        if ((*bytes & 0x80) == 0x00) {
            num = 1;
        } else if ((*bytes & 0xE0) == 0xC0) {
            num = 2;
        } else if ((*bytes & 0xF0) == 0xE0) {
            num = 3;
        } else if ((*bytes & 0xF8) == 0xF0) {
            num = 4;
        } else {
            return false;
        }

        bytes += 1;
        for (int i = 1; i < num; ++i) {
            if ((*bytes & 0xC0) != 0x80) {
                return false;
            }
            bytes += 1;
        }
    }
    return true;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateNextToken(
        JNIEnv *env,
        jobject /* unused */) {
    if (current_position >= DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM) {
        LOGw("%s: Context full! Shifting...", __func__);
        shift_context();
    }

    if (current_position >= stop_generation_position) {
        LOGw("%s: STOP: hitting stop position: %d", __func__, stop_generation_position);
        return nullptr;
    }

    const auto new_token_id = common_sampler_sample(g_sampler, g_context, -1);
    common_sampler_accept(g_sampler, new_token_id, true);

    common_batch_clear(g_batch);
    common_batch_add(g_batch, new_token_id, current_position, {0}, true);
    if (llama_decode(g_context, g_batch) != 0) {
        LOGe("%s: llama_decode() failed for generated token", __func__);
        return nullptr;
    }

    current_position++;

    if (llama_vocab_is_eog(llama_model_get_vocab(g_model), new_token_id)) {
        LOGd("id: %d,\tIS EOG!\nSTOP.", new_token_id);
        chat_add_and_format(ROLE_ASSISTANT, assistant_ss.str());
        return nullptr;
    }

    auto new_token_chars = common_token_to_piece(g_context, new_token_id);
    cached_token_chars += new_token_chars;

    jstring result = nullptr;
    if (is_valid_utf8(cached_token_chars.c_str())) {
        result = env->NewStringUTF(cached_token_chars.c_str());
        LOGv(
                "id: %d,\tcached: `%s`,\tnew: `%s`",
                new_token_id,
                cached_token_chars.c_str(),
                new_token_chars.c_str());

        assistant_ss << cached_token_chars;
        cached_token_chars.clear();
    } else {
        LOGv("id: %d,\tappend to cache", new_token_id);
        result = env->NewStringUTF("");
    }
    return result;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_resetDraftContext(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsystem_prompt,
        jstring juser_prompt,
        jstring jassistant_text,
        jint predict_length) {
    reset_long_term_states();
    reset_short_term_states();

    const auto *system_prompt = env->GetStringUTFChars(jsystem_prompt, nullptr);
    const auto *user_prompt = env->GetStringUTFChars(juser_prompt, nullptr);
    const auto *assistant_text = env->GetStringUTFChars(jassistant_text, nullptr);

    const std::string system(system_prompt ? system_prompt : "");
    const std::string user(user_prompt ? user_prompt : "");
    const std::string assistant(assistant_text ? assistant_text : "");

    if (system_prompt != nullptr) {
        env->ReleaseStringUTFChars(jsystem_prompt, system_prompt);
    }
    if (user_prompt != nullptr) {
        env->ReleaseStringUTFChars(juser_prompt, user_prompt);
    }
    if (assistant_text != nullptr) {
        env->ReleaseStringUTFChars(jassistant_text, assistant_text);
    }

    return reset_draft_context_internal(system, user, assistant, predict_length);
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_startPersistentDraftSession(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsession_id,
        jstring jsystem_prompt,
        jstring juser_prompt,
        jstring jassistant_text,
        jint predict_length) {
    const auto *session_id_chars = env->GetStringUTFChars(jsession_id, nullptr);
    const auto *system_prompt = env->GetStringUTFChars(jsystem_prompt, nullptr);
    const auto *user_prompt = env->GetStringUTFChars(juser_prompt, nullptr);
    const auto *assistant_text = env->GetStringUTFChars(jassistant_text, nullptr);

    const std::string session_id(session_id_chars ? session_id_chars : "");
    const std::string system(system_prompt ? system_prompt : "");
    const std::string user(user_prompt ? user_prompt : "");
    const std::string assistant(assistant_text ? assistant_text : "");

    if (session_id_chars != nullptr) {
        env->ReleaseStringUTFChars(jsession_id, session_id_chars);
    }
    if (system_prompt != nullptr) {
        env->ReleaseStringUTFChars(jsystem_prompt, system_prompt);
    }
    if (user_prompt != nullptr) {
        env->ReleaseStringUTFChars(juser_prompt, user_prompt);
    }
    if (assistant_text != nullptr) {
        env->ReleaseStringUTFChars(jassistant_text, assistant_text);
    }

    if (session_id.empty()) {
        return 1;
    }

    const int reset_result = reset_draft_context_internal(system, user, assistant, predict_length);
    if (reset_result != 0) {
        return 100 + reset_result;
    }

    g_persistent_draft_sessions[session_id] = capture_persistent_draft_session_snapshot(
            capture_prompt_prefix_tokens_from_runtime());
    mark_active_persistent_draft_runtime(session_id, true);
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_restorePersistentDraftSession(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsession_id) {
    const auto *session_id_chars = env->GetStringUTFChars(jsession_id, nullptr);
    const std::string session_id(session_id_chars ? session_id_chars : "");
    if (session_id_chars != nullptr) {
        env->ReleaseStringUTFChars(jsession_id, session_id_chars);
    }

    auto it = g_persistent_draft_sessions.find(session_id);
    if (it == g_persistent_draft_sessions.end()) {
        return 1;
    }
    if (g_sampler != nullptr) {
        common_sampler_reset(g_sampler);
    }
    if (session_id == g_active_persistent_draft_session_id && g_active_runtime_matches_committed_snapshot) {
        return 0;
    }
    if (session_id == g_active_persistent_draft_session_id &&
        rollback_active_runtime_to_committed_snapshot(it->second)) {
        mark_active_persistent_draft_runtime(session_id, true);
        return 0;
    }
    if (!it->second.seq_state_valid) {
        const int predict_length = std::max(
                1,
                static_cast<int>(it->second.host_snapshot.stop_generation_position - it->second.host_snapshot.current_position));
        if (rebuild_runtime_to_token_sequence(
                it->second,
                it->second.host_snapshot.runtime_token_history,
                predict_length)) {
            mark_active_persistent_draft_runtime(session_id, true);
            return 0;
        }
    }
    if (!restore_persistent_draft_session_snapshot(it->second)) {
        clear_active_persistent_draft_runtime();
        return 2;
    }
    mark_active_persistent_draft_runtime(session_id, true);
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_commitPersistentDraftTokens(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsession_id,
        jintArray jtoken_ids,
        jint predict_length) {
    const auto *session_id_chars = env->GetStringUTFChars(jsession_id, nullptr);
    const std::string session_id(session_id_chars ? session_id_chars : "");
    if (session_id_chars != nullptr) {
        env->ReleaseStringUTFChars(jsession_id, session_id_chars);
    }

    auto it = g_persistent_draft_sessions.find(session_id);
    if (it == g_persistent_draft_sessions.end()) {
        return 1;
    }

    if (g_sampler != nullptr) {
        common_sampler_reset(g_sampler);
    }
    const bool restored = (
            session_id == g_active_persistent_draft_session_id &&
            rollback_active_runtime_to_committed_snapshot(it->second))
        || restore_persistent_draft_session_snapshot(it->second);
    if (!restored) {
        clear_active_persistent_draft_runtime();
        return 2;
    }

    const jsize token_count = jtoken_ids == nullptr ? 0 : env->GetArrayLength(jtoken_ids);
    std::vector<jint> token_ids(static_cast<size_t>(std::max<jsize>(0, token_count)));
    if (token_count > 0) {
        env->GetIntArrayRegion(jtoken_ids, 0, token_count, token_ids.data());
    }

    for (const jint raw_token_id : token_ids) {
        if (raw_token_id < 0) {
            continue;
        }
        const llama_token token_id = static_cast<llama_token>(raw_token_id);
        const std::string token_text = common_token_to_piece(g_context, token_id);
        if (!advance_runtime_with_token(token_id, token_text)) {
            return 3;
        }
    }

    stop_generation_position = current_position + std::max(1, static_cast<int>(predict_length));
    it->second = capture_persistent_draft_session_snapshot(it->second.prompt_prefix_tokens);
    mark_active_persistent_draft_runtime(session_id, true);
    return 0;
}

extern "C"
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_syncPersistentDraftSession(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsession_id,
        jintArray jauthoritative_token_ids,
        jint predict_length) {
    const auto *session_id_chars = env->GetStringUTFChars(jsession_id, nullptr);
    const std::string session_id(session_id_chars ? session_id_chars : "");
    if (session_id_chars != nullptr) {
        env->ReleaseStringUTFChars(jsession_id, session_id_chars);
    }

    const auto it = g_persistent_draft_sessions.find(session_id);
    if (it == g_persistent_draft_sessions.end()) {
        return 1;
    }

    const jsize token_count = jauthoritative_token_ids == nullptr ? 0 : env->GetArrayLength(jauthoritative_token_ids);
    std::vector<jint> raw_token_ids(static_cast<size_t>(std::max<jsize>(0, token_count)));
    if (token_count > 0) {
        env->GetIntArrayRegion(jauthoritative_token_ids, 0, token_count, raw_token_ids.data());
    }

    std::vector<llama_token> authoritative_token_ids;
    authoritative_token_ids.reserve(raw_token_ids.size());
    for (const jint raw_token_id : raw_token_ids) {
        if (raw_token_id >= 0) {
            authoritative_token_ids.push_back(static_cast<llama_token>(raw_token_id));
        }
    }

    if (!ensure_runtime_ready_for_authoritative_sync(session_id, it->second)) {
        return 2;
    }

    if (!sync_runtime_to_authoritative_tokens(it->second, authoritative_token_ids, predict_length)) {
        clear_active_persistent_draft_runtime();
        return 3;
    }

    it->second.host_snapshot = capture_host_runtime_snapshot();
    it->second.seq_state_valid = false;
    mark_active_persistent_draft_runtime(session_id, true);
    return 0;
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_closePersistentDraftSession(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsession_id) {
    const auto *session_id_chars = env->GetStringUTFChars(jsession_id, nullptr);
    const std::string session_id(session_id_chars ? session_id_chars : "");
    if (session_id_chars != nullptr) {
        env->ReleaseStringUTFChars(jsession_id, session_id_chars);
    }
    g_persistent_draft_sessions.erase(session_id);
    if (session_id == g_active_persistent_draft_session_id) {
        clear_active_persistent_draft_runtime();
    }
}

extern "C"
JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftTokenIds(
        JNIEnv *env,
        jobject /* unused */,
        jint max_tokens) {
    std::vector<jint> draft_ids;
    draft_ids.reserve(std::max(0, (int) max_tokens));

    for (int step = 0; step < max_tokens; ++step) {
        if (current_position >= DEFAULT_CONTEXT_SIZE - OVERFLOW_HEADROOM) {
            shift_context();
        }

        if (current_position >= stop_generation_position) {
            break;
        }

        const auto new_token_id = common_sampler_sample(g_sampler, g_context, -1);
        common_sampler_accept(g_sampler, new_token_id, true);

        common_batch_clear(g_batch);
        common_batch_add(g_batch, new_token_id, current_position, {0}, true);
        if (llama_decode(g_context, g_batch) != 0) {
            LOGe("%s: llama_decode() failed for draft token", __func__);
            break;
        }

        current_position++;

        if (llama_vocab_is_eog(llama_model_get_vocab(g_model), new_token_id)) {
            chat_add_and_format(ROLE_ASSISTANT, assistant_ss.str());
            break;
        }

        auto new_token_chars = common_token_to_piece(g_context, new_token_id);
        cached_token_chars += new_token_chars;
        if (is_valid_utf8(cached_token_chars.c_str())) {
            const std::string emitted = cached_token_chars;
            assistant_ss << emitted;
            append_utf8_codepoints(emitted, draft_ids);
            cached_token_chars.clear();
        }
    }

    jintArray result = env->NewIntArray((jsize) draft_ids.size());
    if (result == nullptr || draft_ids.empty()) {
        return result;
    }
    env->SetIntArrayRegion(result, 0, (jsize) draft_ids.size(), draft_ids.data());
    return result;
}

extern "C"
JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftRealTokenIds(
        JNIEnv *env,
        jobject /* unused */,
        jint max_tokens) {
    const std::vector<jint> draft_ids = generate_real_draft_token_ids(max_tokens);

    jintArray result = env->NewIntArray((jsize) draft_ids.size());
    if (result == nullptr || draft_ids.empty()) {
        return result;
    }
    env->SetIntArrayRegion(result, 0, (jsize) draft_ids.size(), draft_ids.data());
    return result;
}

extern "C"
JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_syncAndGenerateDraftRealTokenIds(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsession_id,
        jintArray jauthoritative_token_ids,
        jint predict_length,
        jint max_tokens) {
    const auto *session_id_chars = env->GetStringUTFChars(jsession_id, nullptr);
    const std::string session_id(session_id_chars ? session_id_chars : "");
    if (session_id_chars != nullptr) {
        env->ReleaseStringUTFChars(jsession_id, session_id_chars);
    }

    jintArray result = env->NewIntArray(0);
    if (session_id.empty()) {
        return result;
    }

    const auto it = g_persistent_draft_sessions.find(session_id);
    if (it == g_persistent_draft_sessions.end()) {
        return result;
    }

    const jsize token_count = jauthoritative_token_ids == nullptr ? 0 : env->GetArrayLength(jauthoritative_token_ids);
    std::vector<jint> raw_token_ids(static_cast<size_t>(std::max<jsize>(0, token_count)));
    if (token_count > 0) {
        env->GetIntArrayRegion(jauthoritative_token_ids, 0, token_count, raw_token_ids.data());
    }

    std::vector<llama_token> authoritative_token_ids;
    authoritative_token_ids.reserve(raw_token_ids.size());
    for (const jint raw_token_id : raw_token_ids) {
        if (raw_token_id >= 0) {
            authoritative_token_ids.push_back(static_cast<llama_token>(raw_token_id));
        }
    }

    if (!ensure_runtime_ready_for_authoritative_sync(session_id, it->second)) {
        return result;
    }
    if (!sync_runtime_to_authoritative_tokens(it->second, authoritative_token_ids, predict_length)) {
        clear_active_persistent_draft_runtime();
        return result;
    }

    it->second.host_snapshot = capture_host_runtime_snapshot();
    it->second.seq_state_valid = false;
    mark_active_persistent_draft_runtime(session_id, true);

    const std::vector<jint> draft_ids = generate_real_draft_token_ids(max_tokens);
    result = env->NewIntArray((jsize) draft_ids.size());
    if (result == nullptr || draft_ids.empty()) {
        return result;
    }
    env->SetIntArrayRegion(result, 0, (jsize) draft_ids.size(), draft_ids.data());
    return result;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_renderTokenIds(
        JNIEnv *env,
        jobject /* unused */,
        jintArray jtoken_ids) {
    if (g_context == nullptr || g_model == nullptr) {
        return env->NewStringUTF("");
    }

    if (jtoken_ids == nullptr) {
        return env->NewStringUTF("");
    }

    const jsize count = env->GetArrayLength(jtoken_ids);
    if (count <= 0) {
        return env->NewStringUTF("");
    }

    std::vector<jint> raw_ids((size_t) count);
    env->GetIntArrayRegion(jtoken_ids, 0, count, raw_ids.data());

    std::vector<int> token_ids;
    token_ids.reserve(raw_ids.size());
    for (const jint token_id : raw_ids) {
        if (token_id >= 0) {
            token_ids.push_back((int) token_id);
        }
    }

    const std::string text = detokenize_token_ids(token_ids);
    return env->NewStringUTF(text.c_str());
}

extern "C"
JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_commitAndGenerateDraftRealTokenIds(
        JNIEnv *env,
        jobject /* unused */,
        jstring jsession_id,
        jintArray jtoken_ids,
        jint predict_length,
        jint max_tokens) {
    const auto *session_id_chars = env->GetStringUTFChars(jsession_id, nullptr);
    const std::string session_id(session_id_chars ? session_id_chars : "");
    if (session_id_chars != nullptr) {
        env->ReleaseStringUTFChars(jsession_id, session_id_chars);
    }

    jintArray result = env->NewIntArray(0);
    if (session_id.empty()) {
        return result;
    }

    auto it = g_persistent_draft_sessions.find(session_id);
    if (it == g_persistent_draft_sessions.end()) {
        return result;
    }

    if (g_sampler != nullptr) {
        common_sampler_reset(g_sampler);
    }
    const bool restored = (
            session_id == g_active_persistent_draft_session_id &&
            rollback_active_runtime_to_committed_snapshot(it->second))
        || restore_persistent_draft_session_snapshot(it->second);
    if (!restored) {
        clear_active_persistent_draft_runtime();
        return result;
    }

    const jsize token_count = jtoken_ids == nullptr ? 0 : env->GetArrayLength(jtoken_ids);
    std::vector<jint> token_ids(static_cast<size_t>(std::max<jsize>(0, token_count)));
    if (token_count > 0) {
        env->GetIntArrayRegion(jtoken_ids, 0, token_count, token_ids.data());
    }

    for (const jint raw_token_id : token_ids) {
        if (raw_token_id < 0) {
            continue;
        }
        const llama_token token_id = static_cast<llama_token>(raw_token_id);
        const std::string token_text = common_token_to_piece(g_context, token_id);
        if (!advance_runtime_with_token(token_id, token_text)) {
            clear_active_persistent_draft_runtime();
            return result;
        }
    }

    stop_generation_position = current_position + std::max(1, static_cast<int>(predict_length));
    it->second.host_snapshot = capture_host_runtime_snapshot();
    it->second.seq_state_valid = false;
    mark_active_persistent_draft_runtime(session_id, true);

    const std::vector<jint> draft_ids = generate_real_draft_token_ids(max_tokens);
    result = env->NewIntArray((jsize) draft_ids.size());
    if (result == nullptr || draft_ids.empty()) {
        return result;
    }
    env->SetIntArrayRegion(result, 0, (jsize) draft_ids.size(), draft_ids.data());
    return result;
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_debug_DraftRuntimeProbeDemo_nativeCaptureTopKJson(
        JNIEnv *env,
        jobject /* unused */,
        jint top_k) {
    if (g_context == nullptr || g_model == nullptr) {
        return env->NewStringUTF("{\"error\":\"draft runtime is not prepared\"}");
    }

    const int safe_top_k = std::max(1, static_cast<int>(top_k));
    const auto candidates = top_candidates_from_current_logits(safe_top_k);
    std::ostringstream out;
    out << "{"
        << "\"currentPosition\":" << current_position << ","
        << "\"stopGenerationPosition\":" << stop_generation_position << ","
        << "\"topK\":" << safe_top_k << ","
        << "\"candidates\":" << top_candidates_to_json(candidates)
        << "}";
    return env->NewStringUTF(out.str().c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_debug_DraftRuntimeProbeDemo_nativeRunStateRoundTripJson(
        JNIEnv *env,
        jobject /* unused */,
        jint top_k) {
    if (g_context == nullptr || g_model == nullptr) {
        return env->NewStringUTF("{\"error\":\"draft runtime is not prepared\"}");
    }

    const int safe_top_k = std::max(1, static_cast<int>(top_k));
    const auto before = top_candidates_from_current_logits(safe_top_k);

    const size_t state_size = llama_state_get_size(g_context);
    std::vector<uint8_t> state_data(state_size);
    const size_t saved_size = llama_state_get_data(g_context, state_data.data(), state_data.size());

    const host_runtime_probe_snapshot snapshot = capture_host_runtime_snapshot();

    const auto sampled = sample_one_token_for_probe();
    const auto after_sample = top_candidates_from_current_logits(safe_top_k);

    const size_t restored_size = llama_state_set_data(g_context, state_data.data(), saved_size);
    system_prompt_position = snapshot.system_prompt_position;
    current_position = snapshot.current_position;
    stop_generation_position = snapshot.stop_generation_position;
    cached_token_chars = snapshot.cached_token_chars;
    assistant_ss.str("");
    assistant_ss.clear();
    assistant_ss << snapshot.assistant_text;
    runtime_token_history = snapshot.runtime_token_history;

    const bool replay_succeeded = rebuild_logits_cursor_from_snapshot(snapshot);

    const auto after_restore = top_candidates_from_current_logits(safe_top_k);
    const bool restored_matches_before = candidate_vectors_equivalent(before, after_restore);

    std::ostringstream out;
    out << "{"
        << "\"savedStateBytes\":" << saved_size << ","
        << "\"restoredStateBytes\":" << restored_size << ","
        << "\"sampledTokenId\":" << static_cast<int>(sampled.first) << ","
        << "\"sampledTokenText\":\"" << json_escape(sampled.second) << "\","
        << "\"replaySucceeded\":" << (replay_succeeded ? "true" : "false") << ","
        << "\"restoredMatchesBefore\":" << (restored_matches_before ? "true" : "false") << ","
        << "\"before\":" << top_candidates_to_json(before) << ","
        << "\"afterSample\":" << top_candidates_to_json(after_sample) << ","
        << "\"afterRestore\":" << top_candidates_to_json(after_restore)
        << "}";

    return env->NewStringUTF(out.str().c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_debug_DraftRuntimeProbeDemo_nativeRunSequenceStateRoundTripJson(
        JNIEnv *env,
        jobject /* unused */,
        jint top_k) {
    if (g_context == nullptr || g_model == nullptr) {
        return env->NewStringUTF("{\"error\":\"draft runtime is not prepared\"}");
    }

    const int safe_top_k = std::max(1, static_cast<int>(top_k));
    const llama_seq_id seq_id = 0;
    const auto before = top_candidates_from_current_logits(safe_top_k);

    const size_t seq_state_size = llama_state_seq_get_size(g_context, seq_id);
    std::vector<uint8_t> seq_state_data(seq_state_size);
    const size_t saved_size = llama_state_seq_get_data(g_context, seq_state_data.data(), seq_state_data.size(), seq_id);

    const host_runtime_probe_snapshot snapshot = capture_host_runtime_snapshot();

    const auto sampled = sample_one_token_for_probe();
    const auto after_sample = top_candidates_from_current_logits(safe_top_k);

    llama_memory_seq_rm(llama_get_memory(g_context), seq_id, -1, -1);
    const size_t restored_size = llama_state_seq_set_data(g_context, seq_state_data.data(), saved_size, seq_id);
    system_prompt_position = snapshot.system_prompt_position;
    current_position = snapshot.current_position;
    stop_generation_position = snapshot.stop_generation_position;
    cached_token_chars = snapshot.cached_token_chars;
    assistant_ss.str("");
    assistant_ss.clear();
    assistant_ss << snapshot.assistant_text;
    runtime_token_history = snapshot.runtime_token_history;

    const bool replay_succeeded = rebuild_logits_cursor_from_snapshot(snapshot);

    const auto after_restore = top_candidates_from_current_logits(safe_top_k);
    const bool restored_matches_before = candidate_vectors_equivalent(before, after_restore);

    std::ostringstream out;
    out << "{"
        << "\"savedSequenceStateBytes\":" << saved_size << ","
        << "\"restoredSequenceStateBytes\":" << restored_size << ","
        << "\"sequenceId\":" << seq_id << ","
        << "\"sampledTokenId\":" << static_cast<int>(sampled.first) << ","
        << "\"sampledTokenText\":\"" << json_escape(sampled.second) << "\","
        << "\"replaySucceeded\":" << (replay_succeeded ? "true" : "false") << ","
        << "\"restoredMatchesBefore\":" << (restored_matches_before ? "true" : "false") << ","
        << "\"before\":" << top_candidates_to_json(before) << ","
        << "\"afterSample\":" << top_candidates_to_json(after_sample) << ","
        << "\"afterRestore\":" << top_candidates_to_json(after_restore)
        << "}";

    return env->NewStringUTF(out.str().c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftTreeJson(
        JNIEnv *env,
        jobject /* unused */,
        jint max_depth,
        jint branch_factor) {
    const int safe_depth = std::max(1, static_cast<int>(max_depth));
    const int safe_branch_factor = std::max(1, static_cast<int>(branch_factor));
    std::ostringstream nodes_json;
    bool is_first_node = true;
    int global_node_index = 0;
    int depth_evaluated = 0;
    bool best_path_initialized = false;
    int best_path_depth = 0;
    float best_path_score = -std::numeric_limits<float>::infinity();
    std::string best_path_text;
    std::vector<int> best_path_ids;
    std::vector<int> best_path_node_indices;

    std::vector<draft_tree_branch> active_branches;
    active_branches.push_back({
            capture_runtime_branch_snapshot(),
            -1,
            0,
            0.0f,
            "",
            {},
            {}
    });
    const runtime_branch_snapshot root_snapshot = active_branches.front().snapshot;

    for (int depth = 0; depth < safe_depth && !active_branches.empty(); ++depth) {
        std::vector<draft_tree_branch> next_branches;
        bool saw_candidates_at_depth = false;

        for (const auto &branch : active_branches) {
            if (!restore_runtime_branch_snapshot(branch.snapshot)) {
                continue;
            }
            if (current_position >= stop_generation_position) {
                continue;
            }

            const auto candidates = top_candidates_from_current_logits(safe_branch_factor);
            if (candidates.empty()) {
                continue;
            }

            saw_candidates_at_depth = true;
            for (const auto &candidate : candidates) {
                const int node_index = global_node_index++;
                const jint wire_token_id = first_codepoint_id_from_text(candidate.token_text);
                if (!is_first_node) {
                    nodes_json << ",";
                }
                is_first_node = false;
                nodes_json
                        << "{"
                        << "\"nodeIndex\":" << node_index << ","
                        << "\"tokenId\":" << wire_token_id << ","
                        << "\"tokenText\":\"" << json_escape(candidate.token_text) << "\","
                        << "\"depth\":" << depth << ","
                        << "\"parentNodeIndex\":" << branch.parent_node_index << ","
                        << "\"probability\":" << candidate.probability << ","
                        << "\"logProbability\":" << candidate.log_probability << ","
                        << "\"cumulativeLogProbability\":" << (branch.cumulative_log_probability + candidate.log_probability)
                        << "}";

                if (!restore_runtime_branch_snapshot(branch.snapshot)) {
                    continue;
                }
                if (!advance_runtime_with_token(candidate.token_id, candidate.token_text)) {
                    continue;
                }

                draft_tree_branch child_branch {
                        capture_runtime_branch_snapshot(),
                        node_index,
                        depth + 1,
                        branch.cumulative_log_probability + candidate.log_probability,
                        branch.path_text + candidate.token_text,
                        branch.path_ids
                };
                append_utf8_codepoints(candidate.token_text, child_branch.path_ids);
                child_branch.path_node_indices = branch.path_node_indices;
                child_branch.path_node_indices.push_back(node_index);

                if (!best_path_initialized ||
                    child_branch.depth > best_path_depth ||
                    (child_branch.depth == best_path_depth &&
                     child_branch.cumulative_log_probability > best_path_score)) {
                    best_path_initialized = true;
                    best_path_depth = child_branch.depth;
                    best_path_score = child_branch.cumulative_log_probability;
                    best_path_text = child_branch.path_text;
                    best_path_ids = child_branch.path_ids;
                    best_path_node_indices = child_branch.path_node_indices;
                }

                if (!llama_vocab_is_eog(llama_model_get_vocab(g_model), candidate.token_id) &&
                    child_branch.depth < safe_depth &&
                    current_position < stop_generation_position) {
                    next_branches.push_back(std::move(child_branch));
                }
            }
        }

        if (!saw_candidates_at_depth) {
            break;
        }

        depth_evaluated = depth + 1;
        active_branches = std::move(next_branches);
    }

    restore_runtime_branch_snapshot(root_snapshot);

    std::ostringstream result;
    result << "{"
           << "\"tokenMode\":\"codepoint_legacy\","
           << "\"branchFactor\":" << safe_branch_factor << ","
           << "\"depthEvaluated\":" << depth_evaluated << ","
           << "\"bestPathText\":\"" << json_escape(best_path_text) << "\","
           << "\"bestPathTokenIds\":[";
    for (size_t i = 0; i < best_path_ids.size(); ++i) {
        if (i > 0) {
            result << ",";
        }
        result << best_path_ids[i];
    }
    result << "],\"bestPathNodeIndices\":[";
    for (size_t i = 0; i < best_path_node_indices.size(); ++i) {
        if (i > 0) {
            result << ",";
        }
        result << best_path_node_indices[i];
    }
    result << "],\"nodeCount\":" << global_node_index
           << ",\"nodes\":[" << nodes_json.str() << "]"
           << ",\"draftPathSteps\":[]"
           << "}";

    return env->NewStringUTF(result.str().c_str());
}

extern "C"
JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftRealTokenTreeJson(
        JNIEnv *env,
        jobject /* unused */,
        jint max_depth,
        jint branch_factor) {
    const int safe_depth = std::max(1, static_cast<int>(max_depth));
    const int safe_branch_factor = std::max(1, static_cast<int>(branch_factor));
    std::ostringstream nodes_json;
    bool is_first_node = true;
    int global_node_index = 0;
    int depth_evaluated = 0;
    bool best_path_initialized = false;
    int best_path_depth = 0;
    float best_path_score = -std::numeric_limits<float>::infinity();
    std::string best_path_text;
    std::vector<int> best_path_ids;
    std::vector<int> best_path_node_indices;
    std::vector<draft_path_step_record> step_records;

    std::vector<draft_tree_branch> active_branches;
    active_branches.push_back({
            capture_runtime_branch_snapshot(),
            -1,
            0,
            0.0f,
            "",
            {},
            {}
    });
    const runtime_branch_snapshot root_snapshot = active_branches.front().snapshot;

    for (int depth = 0; depth < safe_depth && !active_branches.empty(); ++depth) {
        std::vector<draft_tree_branch> next_branches;
        bool saw_candidates_at_depth = false;

        for (const auto &branch : active_branches) {
            if (!restore_runtime_branch_snapshot(branch.snapshot)) {
                continue;
            }
            if (current_position >= stop_generation_position) {
                continue;
            }

            const auto candidates = top_candidates_from_current_logits(safe_branch_factor);
            if (candidates.empty()) {
                continue;
            }

            saw_candidates_at_depth = true;
            draft_path_step_record *step_record = nullptr;
            for (auto &record : step_records) {
                if (record.depth == depth &&
                    record.parent_node_index == branch.parent_node_index &&
                    record.accepted_prefix_token_ids == branch.path_ids) {
                    step_record = &record;
                    break;
                }
            }
            if (step_record == nullptr) {
                step_records.push_back({
                    depth,
                    branch.parent_node_index,
                    branch.path_ids,
                    {},
                    -1,
                    -1
                });
                step_record = &step_records.back();
            }
            for (const auto &candidate : candidates) {
                const int node_index = global_node_index++;
                step_record->candidates.push_back({
                    node_index,
                    candidate.token_id,
                    candidate.token_text,
                    candidate.probability,
                    candidate.log_probability
                });
                if (!is_first_node) {
                    nodes_json << ",";
                }
                is_first_node = false;
                nodes_json
                        << "{"
                        << "\"nodeIndex\":" << node_index << ","
                        << "\"tokenId\":" << static_cast<int>(candidate.token_id) << ","
                        << "\"tokenText\":\"" << json_escape(candidate.token_text) << "\","
                        << "\"depth\":" << depth << ","
                        << "\"parentNodeIndex\":" << branch.parent_node_index << ","
                        << "\"probability\":" << candidate.probability << ","
                        << "\"logProbability\":" << candidate.log_probability << ","
                        << "\"cumulativeLogProbability\":" << (branch.cumulative_log_probability + candidate.log_probability)
                        << "}";

                if (!restore_runtime_branch_snapshot(branch.snapshot)) {
                    continue;
                }
                if (!advance_runtime_with_token(candidate.token_id, candidate.token_text)) {
                    continue;
                }

                draft_tree_branch child_branch {
                        capture_runtime_branch_snapshot(),
                        node_index,
                        depth + 1,
                        branch.cumulative_log_probability + candidate.log_probability,
                        branch.path_text + candidate.token_text,
                        branch.path_ids
                };
                child_branch.path_ids.push_back(static_cast<int>(candidate.token_id));
                child_branch.path_node_indices = branch.path_node_indices;
                child_branch.path_node_indices.push_back(node_index);

                if (!best_path_initialized ||
                    child_branch.depth > best_path_depth ||
                    (child_branch.depth == best_path_depth &&
                     child_branch.cumulative_log_probability > best_path_score)) {
                    best_path_initialized = true;
                    best_path_depth = child_branch.depth;
                    best_path_score = child_branch.cumulative_log_probability;
                    best_path_text = child_branch.path_text;
                    best_path_ids = child_branch.path_ids;
                    best_path_node_indices = child_branch.path_node_indices;
                }

                if (!llama_vocab_is_eog(llama_model_get_vocab(g_model), candidate.token_id) &&
                    child_branch.depth < safe_depth &&
                    current_position < stop_generation_position) {
                    next_branches.push_back(std::move(child_branch));
                }
            }
        }

        if (!saw_candidates_at_depth) {
            break;
        }

        depth_evaluated = depth + 1;
        active_branches = std::move(next_branches);
    }

    restore_runtime_branch_snapshot(root_snapshot);

    std::vector<draft_path_step_record> best_path_steps;
    int expected_parent_node_index = -1;
    std::vector<int> accepted_prefix_token_ids;
    for (size_t depth = 0; depth < best_path_node_indices.size() && depth < best_path_ids.size(); ++depth) {
        draft_path_step_record *matched_record = nullptr;
        for (auto &record : step_records) {
            if (record.depth == static_cast<int>(depth) &&
                record.parent_node_index == expected_parent_node_index &&
                record.accepted_prefix_token_ids == accepted_prefix_token_ids) {
                matched_record = &record;
                break;
            }
        }
        if (matched_record == nullptr) {
            break;
        }

        draft_path_step_record finalized_record = *matched_record;
        finalized_record.best_node_index = best_path_node_indices[depth];
        finalized_record.best_token_id = best_path_ids[depth];
        best_path_steps.push_back(std::move(finalized_record));

        expected_parent_node_index = best_path_node_indices[depth];
        accepted_prefix_token_ids.push_back(best_path_ids[depth]);
    }

    std::ostringstream result;
    result << "{"
           << "\"tokenMode\":\"real_token\","
           << "\"branchFactor\":" << safe_branch_factor << ","
           << "\"depthEvaluated\":" << depth_evaluated << ","
           << "\"bestPathText\":\"" << json_escape(best_path_text) << "\","
           << "\"bestPathTokenIds\":[";
    for (size_t i = 0; i < best_path_ids.size(); ++i) {
        if (i > 0) {
            result << ",";
        }
        result << best_path_ids[i];
    }
    result << "],\"bestPathNodeIndices\":[";
    for (size_t i = 0; i < best_path_node_indices.size(); ++i) {
        if (i > 0) {
            result << ",";
        }
        result << best_path_node_indices[i];
    }
    result << "],\"nodeCount\":" << global_node_index
           << ",\"nodes\":[" << nodes_json.str() << "]"
           << ",\"draftPathSteps\":";
    append_json_draft_path_steps(result, best_path_steps);
    result << "}";

    return env->NewStringUTF(result.str().c_str());
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_unload(
        JNIEnv * /* unused */,
        jobject /* unused */) {
    reset_long_term_states();
    reset_short_term_states();
    g_persistent_draft_sessions.clear();
    clear_active_persistent_draft_runtime();

    common_sampler_free(g_sampler);
    g_chat_templates.reset();
    llama_batch_free(g_batch);
    llama_free(g_context);
    llama_model_free(g_model);
    g_sampler = nullptr;
    g_context = nullptr;
    g_model = nullptr;
    g_batch = {};
}

extern "C"
JNIEXPORT void JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_shutdown(
        JNIEnv *,
        jobject /* unused */) {
    llama_backend_free();
}
