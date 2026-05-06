#include "common/common.h"
#include "common/chat.h"
#include "common/json-partial.h"
#include "common/sampling.h"
#include "llama.h"

#include <algorithm>
#include <cstdint>
#include <cctype>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

using json = nlohmann::ordered_json;

namespace {

constexpr int DEFAULT_SESSION_N_CTX = 4096;
constexpr int DEFAULT_SESSION_N_BATCH = 512;

struct SessionState {
    std::string session_id;
    std::string system_prompt;
    std::string user_prompt;
    llama_context * ctx = nullptr;
    common_sampler * sampler = nullptr;
    llama_batch batch = {};
    int32_t batch_capacity = DEFAULT_SESSION_N_BATCH;
    std::vector<llama_token> accepted_tokens;
    std::vector<llama_token> prompt_prefix_tokens;
    std::vector<llama_token> anchor_prefix_tokens;
    llama_token anchor_last_token = LLAMA_TOKEN_NULL;
    int32_t anchor_prefix_count = 0;
    std::string replay_prompt;
    std::string sampling_config_key;
    bool fast_path_ready = false;
};

struct RuntimeState {
    llama_model * model = nullptr;
    const llama_vocab * vocab = nullptr;
    common_chat_templates_ptr chat_templates;
    std::string model_path;
    int32_t thread_count = 4;
    std::unordered_map<std::string, SessionState> sessions;
};

RuntimeState g_runtime;

void silent_log_callback(enum ggml_log_level, const char *, void *) {
}

json error_json(const std::string & message) {
    return json{
        {"ok", false},
        {"error", message},
    };
}

json ok_json() {
    return json{
        {"ok", true},
    };
}

std::string normalize_model_path(const std::string & raw_path) {
    if (raw_path.size() >= 3 &&
        std::isalpha(static_cast<unsigned char>(raw_path[0])) &&
        raw_path[1] == ':' &&
        (raw_path[2] == '\\' || raw_path[2] == '/')) {
        std::string normalized = "/mnt/";
        normalized.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(raw_path[0]))));
        for (size_t index = 2; index < raw_path.size(); ++index) {
            const char ch = raw_path[index];
            normalized.push_back(ch == '\\' ? '/' : ch);
        }
        return normalized;
    }
    return raw_path;
}

std::vector<llama_token> json_to_tokens(const json & value) {
    std::vector<llama_token> result;
    if (!value.is_array()) {
        return result;
    }
    result.reserve(value.size());
    for (const auto & item : value) {
        if (item.is_number_integer()) {
            result.push_back(static_cast<llama_token>(item.get<int>()));
        }
    }
    return result;
}

void free_session(SessionState & session) {
    if (session.sampler != nullptr) {
        common_sampler_free(session.sampler);
        session.sampler = nullptr;
    }
    if (session.ctx != nullptr) {
        llama_free(session.ctx);
        session.ctx = nullptr;
    }
    if (session.batch.token != nullptr) {
        llama_batch_free(session.batch);
        session.batch = {};
    }
}

void clear_context(SessionState & session) {
    if (session.ctx != nullptr) {
        llama_memory_clear(llama_get_memory(session.ctx), false);
    }
}

bool decode_tokens(
    SessionState & session,
    const std::vector<llama_token> & tokens,
    int32_t start_pos,
    bool logits,
    std::string & error
) {
    if (tokens.empty()) {
        return true;
    }

    int32_t cursor = 0;
    while (cursor < static_cast<int32_t>(tokens.size())) {
        common_batch_clear(session.batch);
        const int32_t limit = std::min<int32_t>(static_cast<int32_t>(tokens.size()) - cursor, session.batch_capacity);
        for (int32_t index = 0; index < limit; ++index) {
            const bool want_logits = logits;
            common_batch_add(
                session.batch,
                tokens[cursor + index],
                start_pos + cursor + index,
                {0},
                want_logits
            );
        }
        if (llama_decode(session.ctx, session.batch) != 0) {
            error = "llama_decode failed while decoding session tokens.";
            return false;
        }
        cursor += limit;
    }

    return true;
}

std::vector<llama_token> build_known_sequence_tokens(const SessionState & session) {
    std::vector<llama_token> known_tokens = session.prompt_prefix_tokens;
    known_tokens.insert(
        known_tokens.end(),
        session.accepted_tokens.begin(),
        session.accepted_tokens.end()
    );
    return known_tokens;
}

bool restore_anchor_state(SessionState & session, std::string & error) {
    clear_context(session);
    common_sampler_reset(session.sampler);
    const std::vector<llama_token> known_tokens = build_known_sequence_tokens(session);
    for (llama_token token : known_tokens) {
        common_sampler_accept(session.sampler, token, false);
    }
    if (session.anchor_prefix_tokens.empty()) {
        return true;
    }
    if (!decode_tokens(session, session.anchor_prefix_tokens, 0, false, error)) {
        return false;
    }
    return true;
}

common_params_sampling build_sampling_params(const json & sampling_config) {
    common_params_sampling params;
    params.no_perf = false;
    params.seed = sampling_config.value("seed", params.seed);
    params.top_k = sampling_config.value("topK", params.top_k);
    params.top_p = sampling_config.value("topP", params.top_p);
    params.min_p = sampling_config.value("minP", params.min_p);
    params.temp = sampling_config.value("temperature", params.temp);
    params.penalty_last_n = sampling_config.value("penaltyLastN", params.penalty_last_n);
    params.penalty_repeat = sampling_config.value("penaltyRepeat", params.penalty_repeat);
    params.penalty_freq = sampling_config.value("penaltyFreq", params.penalty_freq);
    params.penalty_present = sampling_config.value("penaltyPresent", params.penalty_present);
    return params;
}

std::string sampling_config_key(const json & sampling_config) {
    return sampling_config.is_null() ? std::string("{}") : sampling_config.dump();
}

bool tokenize_chat_fragment(
    const std::string & text,
    bool add_special,
    bool parse_special,
    std::vector<llama_token> & out_tokens
) {
    if (text.empty()) {
        return true;
    }
    const std::vector<llama_token> tokens = common_tokenize(g_runtime.vocab, text, add_special, parse_special);
    out_tokens.insert(out_tokens.end(), tokens.begin(), tokens.end());
    return true;
}

bool build_session_prompt_prefix_tokens(
    const SessionState & session,
    std::vector<llama_token> & prompt_prefix_tokens,
    std::string & replay_prompt,
    std::string & error
) {
    prompt_prefix_tokens.clear();
    std::ostringstream replay_prompt_builder;
    const bool has_chat_template = g_runtime.chat_templates && common_chat_templates_was_explicit(g_runtime.chat_templates.get());
    std::vector<common_chat_msg> chat_msgs;

    if (!session.system_prompt.empty()) {
        std::string formatted_system = session.system_prompt;
        if (has_chat_template) {
            common_chat_msg msg;
            msg.role = "system";
            msg.content = session.system_prompt;
            formatted_system = common_chat_format_single(g_runtime.chat_templates.get(), chat_msgs, msg, false, false);
            chat_msgs.push_back(msg);
        }
        replay_prompt_builder << formatted_system;
        tokenize_chat_fragment(formatted_system, has_chat_template, has_chat_template, prompt_prefix_tokens);
    }

    if (!session.user_prompt.empty()) {
        const bool use_raw_user_prompt = session.system_prompt.empty();
        std::string formatted_user = session.user_prompt;
        if (has_chat_template && !use_raw_user_prompt) {
            common_chat_msg msg;
            msg.role = "user";
            msg.content = session.user_prompt;
            formatted_user = common_chat_format_single(g_runtime.chat_templates.get(), chat_msgs, msg, true, false);
            chat_msgs.push_back(msg);
        }
        const bool tokenize_with_special = use_raw_user_prompt || has_chat_template;
        replay_prompt_builder << formatted_user;
        tokenize_chat_fragment(
            formatted_user,
            tokenize_with_special,
            tokenize_with_special,
            prompt_prefix_tokens
        );
    }

    replay_prompt = replay_prompt_builder.str();
    if (prompt_prefix_tokens.empty()) {
        error = "Replay prompt tokenization produced no tokens.";
        return false;
    }

    return true;
}

bool rebuild_session_anchor(SessionState & session, std::string & error) {
    clear_context(session);
    common_sampler_reset(session.sampler);

    std::vector<llama_token> prompt_prefix_tokens;
    if (!build_session_prompt_prefix_tokens(session, prompt_prefix_tokens, session.replay_prompt, error)) {
        return false;
    }
    session.prompt_prefix_tokens = prompt_prefix_tokens;

    const std::vector<llama_token> known_tokens = build_known_sequence_tokens(session);
    if (known_tokens.empty()) {
        error = "Known session token sequence is empty.";
        return false;
    }

    const std::string accepted_text = common_detokenize(g_runtime.vocab, session.accepted_tokens, true);
    if (!accepted_text.empty()) {
        session.replay_prompt += accepted_text;
    }

    session.anchor_last_token = known_tokens.back();
    session.anchor_prefix_count = std::max<int32_t>(0, static_cast<int32_t>(known_tokens.size()) - 1);
    session.anchor_prefix_tokens.assign(known_tokens.begin(), known_tokens.end() - 1);
    session.fast_path_ready = false;

    return true;
}

bool initialize_fast_path(SessionState & session, std::string & error) {
    clear_context(session);
    common_sampler_reset(session.sampler);
    const std::vector<llama_token> known_tokens = build_known_sequence_tokens(session);
    for (llama_token token : known_tokens) {
        common_sampler_accept(session.sampler, token, false);
    }
    if (!session.anchor_prefix_tokens.empty() &&
        !decode_tokens(session, session.anchor_prefix_tokens, 0, false, error)) {
        return false;
    }
    session.fast_path_ready = true;
    return true;
}

bool rebuild_and_restore_session(SessionState & session, std::string & error) {
    if (!rebuild_session_anchor(session, error)) {
        return false;
    }
    return initialize_fast_path(session, error);
}

bool ensure_model_loaded(std::string & error) {
    if (g_runtime.model != nullptr) {
        return true;
    }
    error = "Target model is not loaded.";
    return false;
}

json handle_load_model(const json & request) {
    const std::string model_path = normalize_model_path(request.value("modelPath", ""));
    const int32_t thread_count = std::max(1, request.value("threadCount", g_runtime.thread_count));
    if (model_path.empty()) {
        return error_json("modelPath is required.");
    }

    if (g_runtime.model != nullptr && g_runtime.model_path == model_path) {
        auto response = ok_json();
        response["status"] = "already_loaded";
        response["modelPath"] = g_runtime.model_path;
        return response;
    }

    for (auto & entry : g_runtime.sessions) {
        free_session(entry.second);
    }
    g_runtime.sessions.clear();

    if (g_runtime.model != nullptr) {
        llama_model_free(g_runtime.model);
        g_runtime.model = nullptr;
        g_runtime.vocab = nullptr;
        g_runtime.chat_templates.reset();
        g_runtime.model_path.clear();
    }

    llama_model_params model_params = llama_model_default_params();
    g_runtime.model = llama_model_load_from_file(model_path.c_str(), model_params);
    if (g_runtime.model == nullptr) {
        return error_json("Failed to load model from modelPath.");
    }

    g_runtime.vocab = llama_model_get_vocab(g_runtime.model);
    g_runtime.chat_templates = common_chat_templates_init(g_runtime.model, "");
    g_runtime.model_path = model_path;
    g_runtime.thread_count = thread_count;

    auto response = ok_json();
    response["status"] = "loaded";
    response["modelPath"] = g_runtime.model_path;
    response["threadCount"] = g_runtime.thread_count;
    response["nCtxTrain"] = llama_model_n_ctx_train(g_runtime.model);
    response["vocabSize"] = llama_vocab_n_tokens(g_runtime.vocab);
    return response;
}

json handle_start_session(const json & request) {
    std::string error;
    if (!ensure_model_loaded(error)) {
        return error_json(error);
    }

    const std::string session_id = request.value("sessionId", "");
    if (session_id.empty()) {
        return error_json("sessionId is required.");
    }

    const std::string system_prompt = request.value("systemPrompt", "");
    const std::string user_prompt = request.value("userPrompt", "");

    auto existing = g_runtime.sessions.find(session_id);
    if (existing != g_runtime.sessions.end()) {
        free_session(existing->second);
        g_runtime.sessions.erase(existing);
    }

    llama_context_params ctx_params = llama_context_default_params();
    // The verifier fast path only needs a modest live context window for the
    // replayed prompt + accepted prefix. Allocating up to the model's training
    // context here can trigger huge, unnecessary KV reservations and make
    // start_session unstable under the desktop helper.
    ctx_params.n_ctx = std::min<int32_t>(
        DEFAULT_SESSION_N_CTX,
        static_cast<int32_t>(llama_model_n_ctx_train(g_runtime.model))
    );
    ctx_params.n_batch = DEFAULT_SESSION_N_BATCH;
    ctx_params.n_threads = g_runtime.thread_count;
    ctx_params.n_threads_batch = g_runtime.thread_count;
    ctx_params.no_perf = false;

    SessionState session;
    session.session_id = session_id;
    session.system_prompt = system_prompt;
    session.user_prompt = user_prompt;
    session.ctx = llama_init_from_model(g_runtime.model, ctx_params);
    if (session.ctx == nullptr) {
        return error_json("Failed to create llama_context for speculative session.");
    }

    session.batch = llama_batch_init(DEFAULT_SESSION_N_BATCH, 0, 1);
    const json sampling_config = request.value("samplingConfig", json::object());
    common_params_sampling sampling_params = build_sampling_params(sampling_config);
    sampling_params.no_perf = false;
    session.sampler = common_sampler_init(g_runtime.model, sampling_params);
    if (session.sampler == nullptr) {
        free_session(session);
        return error_json("Failed to create speculative sampler.");
    }

    session.sampling_config_key = sampling_config_key(sampling_config);

    if (!rebuild_and_restore_session(session, error)) {
        free_session(session);
        return error_json(error);
    }

    g_runtime.sessions.emplace(session_id, std::move(session));
    auto & stored = g_runtime.sessions.at(session_id);

    auto response = ok_json();
    response["status"] = "ready";
    response["sessionId"] = stored.session_id;
    response["acceptedTokenIds"] = json::array();
    response["acceptedText"] = "";
    response["replayPrompt"] = stored.replay_prompt;
    response["targetPreviewText"] = "";
    response["runtimeBackend"] = "desktop_target_runtime_llama_cpp_spec_native";
    return response;
}

json handle_render_tokens(const json & request) {
    std::string error;
    if (!ensure_model_loaded(error)) {
        return error_json(error);
    }

    const std::vector<llama_token> tokens = json_to_tokens(request.value("tokenIds", json::array()));
    auto response = ok_json();
    response["text"] = common_detokenize(g_runtime.vocab, tokens, true);
    return response;
}

json handle_tokenize_text(const json & request) {
    std::string error;
    if (!ensure_model_loaded(error)) {
        return error_json(error);
    }

    const std::string text = request.value("text", "");
    const bool add_special = request.value("addSpecial", false);
    const bool parse_special = request.value("parseSpecial", true);
    const std::vector<llama_token> tokens = common_tokenize(g_runtime.vocab, text, add_special, parse_special);

    auto response = ok_json();
    response["tokenIds"] = tokens;
    return response;
}

json handle_verify_draft_batch(const json & request, const bool split_mode = false) {
    std::string error;
    if (!ensure_model_loaded(error)) {
        return error_json(error);
    }
    const int64_t t_helper_begin_us = ggml_time_us();

    const std::string session_id = request.value("sessionId", "");
    if (session_id.empty()) {
        return error_json("sessionId is required.");
    }

    auto it = g_runtime.sessions.find(session_id);
    if (it == g_runtime.sessions.end()) {
        return error_json("Unknown target session.");
    }
    auto & session = it->second;

    const std::vector<llama_token> request_accepted = json_to_tokens(request.value("acceptedTokenIds", json::array()));
    if (!split_mode && request.contains("acceptedTokenIds") && request_accepted != session.accepted_tokens) {
        session.accepted_tokens = request_accepted;
        if (!rebuild_and_restore_session(session, error)) {
            return error_json(error);
        }
    }

    const std::vector<llama_token> draft_tokens = json_to_tokens(request.value("draftTokenIds", json::array()));
    if (draft_tokens.empty()) {
        return error_json("draftTokenIds must not be empty.");
    }

    const json sampling_config = request.value("samplingConfig", json::object());
    const std::string requested_sampling_key = sampling_config_key(sampling_config);
    const int64_t t_prepare_begin_us = ggml_time_us();
    const bool fast_path_was_ready = session.fast_path_ready;
    bool sampler_rebuilt = false;
    bool fast_path_reinitialized = false;
    if (requested_sampling_key != session.sampling_config_key) {
        const common_params_sampling sampling_params = build_sampling_params(sampling_config);
        common_sampler_free(session.sampler);
        session.sampler = common_sampler_init(g_runtime.model, const_cast<common_params_sampling &>(sampling_params));
        if (session.sampler == nullptr) {
            return error_json("Failed to rebuild speculative sampler for verify_draft_batch.");
        }
        sampler_rebuilt = true;
        session.sampling_config_key = requested_sampling_key;
        if (!rebuild_and_restore_session(session, error)) {
            return error_json(error);
        }
    } else if (!session.fast_path_ready) {
        fast_path_reinitialized = true;
        if (!initialize_fast_path(session, error)) {
            return error_json(error);
        }
    }
    const int64_t t_prepare_end_us = ggml_time_us();

    const int64_t t_decode_begin_us = ggml_time_us();
    common_batch_clear(session.batch);
    common_batch_add(
        session.batch,
        session.anchor_last_token,
        session.anchor_prefix_count,
        {0},
        true
    );
    for (size_t index = 0; index < draft_tokens.size(); ++index) {
        common_batch_add(
            session.batch,
            draft_tokens[index],
            session.anchor_prefix_count + 1 + static_cast<int32_t>(index),
            {0},
            true
        );
    }

    if (llama_decode(session.ctx, session.batch) != 0) {
        return error_json("llama_decode failed during verify_draft_batch.");
    }
    const int64_t t_decode_end_us = ggml_time_us();

    std::vector<int> idxs(draft_tokens.size() + 1);
    for (size_t index = 0; index < idxs.size(); ++index) {
        idxs[index] = static_cast<int>(index);
    }

    const int64_t t_sample_begin_us = ggml_time_us();
    const std::vector<llama_token> sampled_tokens = common_sampler_sample_and_accept_n(
        session.sampler,
        session.ctx,
        idxs,
        draft_tokens
    );
    const int64_t t_sample_end_us = ggml_time_us();

    if (sampled_tokens.empty()) {
        return error_json("Target sampling returned no tokens.");
    }

    int accepted_draft_count = 0;
    while (accepted_draft_count < static_cast<int>(draft_tokens.size()) &&
           accepted_draft_count < static_cast<int>(sampled_tokens.size()) &&
           sampled_tokens[accepted_draft_count] == draft_tokens[accepted_draft_count]) {
        ++accepted_draft_count;
    }
    const bool fully_accepted =
        accepted_draft_count == static_cast<int>(draft_tokens.size()) &&
        sampled_tokens.size() == draft_tokens.size() + 1;

    std::vector<llama_token> accepted_tokens;
    accepted_tokens.reserve(static_cast<size_t>(accepted_draft_count));
    for (int index = 0; index < accepted_draft_count; ++index) {
        accepted_tokens.push_back(draft_tokens[index]);
    }

    const llama_token followup_token = sampled_tokens.back();
    std::vector<llama_token> returned_tokens = accepted_tokens;
    returned_tokens.push_back(followup_token);

    session.anchor_prefix_tokens.push_back(session.anchor_last_token);
    session.anchor_prefix_tokens.insert(
        session.anchor_prefix_tokens.end(),
        accepted_tokens.begin(),
        accepted_tokens.end()
    );
    session.anchor_prefix_count = static_cast<int32_t>(session.anchor_prefix_tokens.size());
    session.anchor_last_token = followup_token;
    session.accepted_tokens.insert(session.accepted_tokens.end(), returned_tokens.begin(), returned_tokens.end());
    const int64_t t_rollback_begin_us = ggml_time_us();
    if (!llama_memory_seq_rm(
            llama_get_memory(session.ctx),
            0,
            session.anchor_prefix_count,
            -1)) {
        session.fast_path_ready = false;
        if (!rebuild_and_restore_session(session, error)) {
            return error_json("Failed to trim speculative verifier tail and could not rebuild fast path.");
        }
    }
    const int64_t t_rollback_end_us = ggml_time_us();
    session.fast_path_ready = true;
    const int64_t t_helper_end_us = ggml_time_us();

    auto response = ok_json();
    response["acceptedTokenIds"] = accepted_tokens;
    response["acceptedCount"] = accepted_draft_count;
    response["followupTokenId"] = static_cast<int>(followup_token);
    response["correctionTokenIds"] = json::array({static_cast<int>(followup_token)});
    response["returnedTokenIds"] = returned_tokens;
    response["rejectedFromIndex"] = fully_accepted ? -1 : accepted_draft_count;
    response["targetTextDelta"] = common_detokenize(g_runtime.vocab, returned_tokens, true);
    response["targetSampledTokenIds"] = sampled_tokens;
    // The service can reconstruct cumulative accepted text by appending the
    // per-step delta, so avoid an O(prefix) detokenize on every helper round.
    response["acceptedTextAfterStep"] = "";
    response["finishReason"] = "";
    response["targetIndexBeforeStep"] = static_cast<int>(session.accepted_tokens.size() - returned_tokens.size());
    response["targetRemainingCount"] = 0;
    response["targetPreviewDebug"] = "";
    response["runtimeBackend"] = split_mode
        ? "desktop_target_runtime_llama_cpp_spec_split"
        : "desktop_target_runtime_llama_cpp_spec_native";
    response["debug"] = json{
        {"draftCount", static_cast<int>(draft_tokens.size())},
        {"acceptedDraftCount", accepted_draft_count},
        {"rolledBackDraftCount", static_cast<int>(draft_tokens.size()) - accepted_draft_count},
        {"usedSpeculative", true},
        {"llamaCppStyleMode", true},
        {"splitContractMode", split_mode},
        {"fastPathWasReady", fast_path_was_ready},
        {"fastPathReadyAfterPrepare", session.fast_path_ready},
        {"samplerRebuilt", sampler_rebuilt},
        {"fastPathReinitialized", fast_path_reinitialized},
        {"timingPrepareMs", (t_prepare_end_us - t_prepare_begin_us) / 1000.0},
        {"timingDecodeMs", (t_decode_end_us - t_decode_begin_us) / 1000.0},
        {"timingSampleMs", (t_sample_end_us - t_sample_begin_us) / 1000.0},
        {"timingRollbackMs", (t_rollback_end_us - t_rollback_begin_us) / 1000.0},
        {"timingHelperTotalMs", (t_helper_end_us - t_helper_begin_us) / 1000.0},
    };
    return response;
}

json handle_close_session(const json & request) {
    const std::string session_id = request.value("sessionId", "");
    if (session_id.empty()) {
        return error_json("sessionId is required.");
    }

    auto it = g_runtime.sessions.find(session_id);
    if (it != g_runtime.sessions.end()) {
        free_session(it->second);
        g_runtime.sessions.erase(it);
    }

    auto response = ok_json();
    response["status"] = "closed";
    response["sessionId"] = session_id;
    return response;
}

json handle_request(const json & request) {
    const std::string command = request.value("command", "");
    if (command == "load_model") {
        return handle_load_model(request);
    }
    if (command == "start_session") {
        return handle_start_session(request);
    }
    if (command == "verify_draft_batch") {
        return handle_verify_draft_batch(request, false);
    }
    if (command == "verify_split_draft_batch") {
        return handle_verify_draft_batch(request, true);
    }
    if (command == "render_tokens") {
        return handle_render_tokens(request);
    }
    if (command == "tokenize_text") {
        return handle_tokenize_text(request);
    }
    if (command == "close_session") {
        return handle_close_session(request);
    }
    if (command == "shutdown") {
        auto response = ok_json();
        response["status"] = "shutdown";
        return response;
    }
    return error_json("Unknown helper command.");
}

} // namespace

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    llama_backend_init();
    llama_log_set(silent_log_callback, nullptr);

    std::string line;
    while (std::getline(std::cin, line)) {
        json response;
        try {
            response = handle_request(json::parse(line));
        } catch (const std::exception & exc) {
            response = error_json(std::string("Exception while handling helper command: ") + exc.what());
        }

        std::cout << response.dump() << std::endl;
        if (response.value("status", "") == "shutdown") {
            break;
        }
    }

    for (auto & entry : g_runtime.sessions) {
        free_session(entry.second);
    }
    g_runtime.sessions.clear();
    if (g_runtime.model != nullptr) {
        llama_model_free(g_runtime.model);
        g_runtime.model = nullptr;
    }
    llama_backend_free();
    return 0;
}
