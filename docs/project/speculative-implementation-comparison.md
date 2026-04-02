# Speculative Implementation Comparison

## Purpose

This document compares three speculative-decoding implementation styles that now matter to this project:

1. `Android-Speculative-Inference` demo
2. upstream `llama.cpp` speculative decoding
3. the current project `llama_cpp_spec_native` implementation
4. `spec-split-demo-project`

The goal is not to decide which code is "better" in the abstract.

The goal is to make it easy to answer:

- which runtime model each implementation actually uses
- which code path is carrying the draft state
- which code path is carrying the verifier state
- why upstream `llama.cpp` behaves differently from the earlier demo
- why the current project is closer to upstream than to the older demo, while still carrying extra cross-device cost

## Reading Rule

Each section includes:

1. original code snippet
2. what the code actually does
3. what that means for the implementation model

## 1. `Android-Speculative-Inference` Demo

### 1.1 Android Draft Session Model

File:

- `reference/Android-Speculative-Inference/lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`

Core code:

```kotlin
override suspend fun startDraftSession(
    systemPrompt: String,
    userPrompt: String,
    predictLength: Int
): DraftSessionHandle = withContext(llamaDispatcher) {
    val sessionId = UUID.randomUUID().toString()
    val runtime = DraftSessionRuntime(
        sessionId = sessionId,
        systemPrompt = systemPrompt,
        userPrompt = userPrompt,
        predictLength = predictLength
    )
    resetDraftRuntime(runtime)
    draftSessions[sessionId] = runtime
    DraftSessionHandle(
        sessionId = sessionId,
        runtimeLabel = "ai-chat draft session",
        acceptedText = runtime.acceptedText,
        acceptedTokenCount = runtime.acceptedText.codePointCount(0, runtime.acceptedText.length)
    )
}

override suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
    resetDraftRuntime(runtime)
    generateDraftTokenIds(maxTokens).toList()
}
```

Explanation:

- The demo draft session is a Kotlin-side shell around:
  - `systemPrompt`
  - `userPrompt`
  - `acceptedText`
- Before every draft fetch, it rebuilds the native draft runtime from that text state.
- The session model is simple and easy to reason about, but it is replay-based.

Implementation meaning:

- This is a clean demo shape for separating draft and verifier roles.
- It is not a persistent native draft runtime in the upstream `llama.cpp` sense.

### 1.2 Android Draft Token Production

File:

- `reference/Android-Speculative-Inference/lib/src/main/cpp/ai_chat.cpp`

Core code:

```cpp
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
    ...
    const int system_result = process_prompt_text(system, ROLE_SYSTEM, true);
    const int user_result = process_prompt_text(user, ROLE_USER, false, true);
    const int assistant_result = process_prompt_text(assistant, ROLE_ASSISTANT, false);
    stop_generation_position = current_position + std::max(1, (int) predict_length);
    return 0;
}

JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftTokenIds(
        JNIEnv *env,
        jobject /* unused */,
        jint max_tokens) {
    for (int step = 0; step < max_tokens; ++step) {
        const auto new_token_id = common_sampler_sample(g_sampler, g_context, -1);
        common_sampler_accept(g_sampler, new_token_id, true);
        common_batch_add(g_batch, new_token_id, current_position, {0}, true);
        llama_decode(g_context, g_batch);
        ...
        draft_ids.push_back((jint) codepoint);
    }
}
```

Explanation:

- The draft runtime is rebuilt from prompt text and accepted assistant text.
- Draft generation itself is light:
  - ordinary sampler path
  - ordinary decode path
- But the produced ids are codepoint-compatible wire ids, not real `llama_token` ids.

Implementation meaning:

- This demo optimizes for a simple split architecture.
- It does not optimize for token-native correctness or upstream speculative parity.

### 1.3 Verifier Shape

File:

- `reference/Android-Speculative-Inference/tools/desktop_inference_service.py`

Core code:

```python
def propose_speculative_tokens(server: "InferenceServer", payload: dict[str, Any]) -> dict[str, Any]:
    ...
    proposed_token_ids = parse_int_list("proposedTokenIds", payload.get("proposedTokenIds"))
    ...
    if session.verifier_mode == "llama_true_step":
        computation = compute_true_verifier_result(...)
    elif session.verifier_mode == "llama_true_tree":
        computation = compute_true_tree_verifier_result(...)
    else:
        computation = compute_proxy_verifier_result(...)
```

Explanation:

- The verifier is orchestrated in Python.
- Android sends draft tokens to the service.
- The service computes accept/correct results and updates session state.

Implementation meaning:

- This is a service-shell verifier architecture.
- It is good for protocol exploration.
- It is not the same thing as an in-process, token-native, persistent verifier runtime.

## 2. Upstream `llama.cpp`

### 2.1 Target-Side Main Loop

File:

- `reference/llama.cpp-upstream/examples/speculative-simple/speculative-simple.cpp`

Core code:

```cpp
llama_tokens draft = common_speculative_draft(spec, params_spec, prompt_tgt, id_last);

common_batch_clear(batch_tgt);
common_batch_add(batch_tgt, id_last, n_past++, { 0 }, true);

if (draft.size() < (size_t) params_spec.n_min) {
    draft.clear();
}

for (size_t i = 0; i < draft.size(); ++i) {
    common_batch_add(batch_tgt, draft[i], n_past + i, { 0 }, true);
}

llama_decode(ctx_tgt, batch_tgt);

const auto ids = common_sampler_sample_and_accept_n(smpl, ctx_tgt, draft);
...
llama_memory_seq_rm(llama_get_memory(ctx_tgt), 0, n_past, -1);
```

Explanation:

- The target context stays alive inside one process.
- The verifier evaluates `[id_last + draft...]` directly in the target context.
- `common_sampler_sample_and_accept_n(...)` implements longest-prefix acceptance plus one more target token.
- After the step, upstream removes only the extra tail from the target KV cache.

Implementation meaning:

- This is the closest reference for the project's `llama_cpp_spec_native` goal.
- It is persistent-state, token-native, and verifier-runtime-oriented.

### 2.2 Draft-Side State Reuse

File:

- `reference/llama.cpp-upstream/common/speculative.cpp`

Core code:

```cpp
int reuse_i = 0;
int reuse_n = 0;

for (int i = 0; i < (int) prompt_dft.size(); ++i) {
    int cur = 0;
    while (i_start + cur < (int) prompt_cur.size() &&
            i       + cur < (int) prompt_dft.size() &&
            prompt_cur[i_start + cur] == prompt_dft[i + cur]) {
        cur++;
    }

    if ((cur >= 256 || n_ctx >= (int) prompt_cur.size()) && cur > reuse_n) {
        reuse_i = i;
        reuse_n = cur;
    }
}

if (reuse_i > 0) {
    llama_memory_seq_rm (mem_dft, 0, 0, reuse_i);
    llama_memory_seq_add(mem_dft, 0, reuse_i, -1, -reuse_i);
    prompt_dft.erase(prompt_dft.begin(), prompt_dft.begin() + reuse_i);
}

if (reuse_n < (int) prompt_dft.size()) {
    llama_memory_seq_rm (mem_dft, 0, reuse_n, -1);
    prompt_dft.erase(prompt_dft.begin() + reuse_n, prompt_dft.end());
}
```

Explanation:

- Upstream does not rebuild draft state from text for each step.
- It reuses as much of the old draft context as possible.
- It trims and shifts only the parts that are no longer valid.

Implementation meaning:

- This is a real runtime continuity design.
- It is much closer to KV reuse than to replay/reset semantics.

### 2.3 Draft Token Selection

File:

- `reference/llama.cpp-upstream/common/speculative.cpp`

Core code:

```cpp
common_sampler_reset(smpl);

for (int i = 0; i < params.n_max; ++i) {
    common_batch_clear(batch);

    common_sampler_sample(smpl, ctx_dft, 0, true);

    const auto * cur_p = common_sampler_get_candidates(smpl, true);
    const llama_token id = cur_p->data[0].id;

    common_sampler_accept(smpl, id, true);
    result.push_back(id);

    if (cur_p->data[0].p < params.p_min) {
        break;
    }

    common_batch_add(batch, id, n_past + i + 1, { 0 }, true);
    llama_decode(ctx_dft, batch);
}
```

Explanation:

- Draft token generation uses the sampler's own candidate buffer.
- It does not manually scan the entire vocabulary and recompute top-k/softmax in project code.
- The sampler is persistent and is reset, not rebuilt, for ordinary draft rounds.

Implementation meaning:

- Upstream is optimized around light hot-path token production.
- This is one of the reasons it does not suffer from the same draft degradation pattern as a replay-heavy service demo.

## 3. Current Project `llama_cpp_spec_native`

### 3.1 Android Real-Token Draft Session

File:

- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`

Core code:

```kotlin
val startResult = startPersistentDraftSession(
    sessionId = sessionId,
    systemPrompt = systemPrompt,
    userPrompt = userPrompt,
    assistantText = runtime.acceptedText,
    predictLength = runtime.predictLength
)

override suspend fun draftNextRealTokenIds(sessionId: String, maxTokens: Int): List<Int> = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
    restorePersistentRuntime(runtime)
    generateDraftRealTokenIds(maxTokens).toList()
}

override suspend fun applyVerifiedRealTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle = withContext(llamaDispatcher) {
    val safeTokenIds = tokenIds.filter { it >= 0 }
    val commitResult = commitPersistentDraftTokens(
        sessionId = sessionId,
        tokenIds = safeTokenIds.toIntArray(),
        predictLength = runtime.predictLength
    )
    ...
}
```

Explanation:

- The current project no longer treats the real-token draft path as a pure replay shell.
- It creates a native persistent draft session, restores it for draft fetch, and commits verifier-approved tokens back into native state.
- The draft state is token-native, not codepoint-only.

Implementation meaning:

- This is structurally closer to upstream than to the older demo.
- But it still carries cross-device orchestration and Android-specific persistence overhead that upstream does not have.

### 3.2 Android Native Draft Persistence

File:

- `lib/src/main/cpp/ai_chat.cpp`

Core code:

```cpp
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_startPersistentDraftSession(...) {
    const int reset_result = reset_draft_context_internal(system, user, assistant, predict_length);
    g_persistent_draft_sessions[session_id] = capture_persistent_draft_session_snapshot();
    return 0;
}

JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_restorePersistentDraftSession(...) {
    if (g_sampler != nullptr) {
        common_sampler_reset(g_sampler);
    }
    return restore_persistent_draft_session_snapshot(it->second) ? 0 : 2;
}

JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_commitPersistentDraftTokens(...) {
    if (!restore_persistent_draft_session_snapshot(it->second)) {
        return 2;
    }
    ...
    it->second = capture_persistent_draft_session_snapshot();
    return 0;
}
```

Explanation:

- The current project moved from full text replay toward native snapshot persistence.
- It now stores draft-session state inside native code instead of rebuilding only from Kotlin text fields every time.
- This is still heavier than upstream KV reuse, but it is already beyond the old demo model.

Implementation meaning:

- This is a parity-seeking intermediate design:
  - closer to upstream than reset-only replay
  - still not as light as upstream's direct context reuse

### 3.3 Current Real-Token Draft Generation

File:

- `lib/src/main/cpp/ai_chat.cpp`

Core code:

```cpp
static bool next_real_draft_candidate(llama_token &out_token_id, std::string &out_token_text, float &out_probability) {
    out_token_id = common_sampler_sample(g_sampler, g_context, -1, true);
    ...
    auto * candidates = common_sampler_get_candidates(g_sampler, true);
    ...
}
```

Explanation:

- The current project originally used a much heavier full-vocabulary candidate extraction path.
- It has now been moved closer to upstream by using the sampler's existing candidate buffer.
- This reduces one of the major Android draft hot-path costs.

Implementation meaning:

- The project is actively converging toward upstream speculative draft mechanics.
- This is one of the strongest signs that the current mainline is no longer the same class of implementation as the old demo.

### 3.4 Desktop Native Helper Verifier

File:

- `tools/desktop_target_runtime.cpp`

Core code:

```cpp
if (requested_sampling_key != session.sampling_config_key) {
    common_sampler_free(session.sampler);
    session.sampler = common_sampler_init(...);
    if (!rebuild_and_restore_session(session, error)) {
        return error_json(error);
    }
} else if (!session.fast_path_ready) {
    if (!initialize_fast_path(session, error)) {
        return error_json(error);
    }
}

const std::vector<llama_token> sampled_tokens = common_sampler_sample_and_accept_n(
    session.sampler,
    session.ctx,
    idxs,
    draft_tokens
);

session.anchor_prefix_tokens.push_back(session.anchor_last_token);
session.anchor_prefix_tokens.insert(
    session.anchor_prefix_tokens.end(),
    accepted_tokens.begin(),
    accepted_tokens.end()
);
session.anchor_last_token = followup_token;
llama_memory_seq_rm(llama_get_memory(session.ctx), 0, session.anchor_prefix_count, -1);
```

Explanation:

- The desktop verifier helper is now built around a persistent native session.
- It reuses sampler state when possible.
- It verifies draft batches through `common_sampler_sample_and_accept_n(...)`.
- It trims only the temporary verifier tail after a step.

Implementation meaning:

- This is directly modeled after upstream `llama.cpp` verifier behavior.
- It is much closer to the upstream runtime than to the Python-shell verifier in the older demo.

## 4. Direct Comparison

## 4. `spec-split-demo-project`

### 4.1 Project Goal And Communication Shape

File:

- `reference/spec-split-demo-project/README.md`

Core code:

```md
This demo shows how to separate speculative drafting and verification into two independent processes.

- `draft_side.py` only proposes draft tokens and writes a proposal file.
- `verify_side.py` reads the proposal, verifies it against a target stream, appends accepted output to a document, and writes a decision file.

Communication is done through shared files:

- `shared/state.json`
- `shared/proposal.json`
- `shared/decision.json`
- `shared/document.md`
```

Explanation:

- This project is an explicit split-process protocol demo.
- It is not real model inference.
- It uses a file bus instead of JNI, HTTP, or in-process contexts.

Implementation meaning:

- This is the cleanest possible architecture demo for "draft side" and "verify side" separation.
- It is even further from upstream `llama.cpp` runtime behavior than the earlier Android demo.

### 4.2 Draft Side

File:

- `reference/spec-split-demo-project/draft_side.py`

Core code:

```python
def make_draft(target_tokens, accepted_pos: int, n_max: int, rng: random.Random):
    start = accepted_pos + 1
    end = min(start + n_max, len(target_tokens))
    draft = target_tokens[start:end]
    if not draft:
        return draft

    if rng.random() < MISMATCH_PROB:
        i = rng.randrange(len(draft))
        draft[i] = "<WRONG>"
    return draft

...

proposal = {
    "round": round_id,
    "accepted_pos": accepted_pos,
    "id_last": id_last,
    "draft_tokens": draft_tokens,
    "n_max": N_MAX,
}
write_json(PROPOSAL, proposal)
```

Explanation:

- The draft worker does not run a model.
- It simply slices the known target token stream and sometimes injects a deterministic wrong token.
- It writes proposals to a shared file for the verifier to consume.

Implementation meaning:

- This is a protocol mock, not a draft runtime.
- It is useful for understanding speculative message flow, but it says nothing about model-state reuse, sampler cost, or KV continuity.

### 4.3 Verifier Side

File:

- `reference/spec-split-demo-project/verify_side.py`

Core code:

```python
def verify_like_sample_and_accept_n(target_tokens, accepted_pos, draft_tokens):
    result = []
    i = 0
    while i < len(draft_tokens):
        pos = accepted_pos + i + 1
        if pos >= len(target_tokens):
            break
        sampled = target_tokens[pos]
        result.append(sampled)
        if draft_tokens[i] != sampled:
            break
        i += 1

    if i == len(draft_tokens):
        pos = accepted_pos + i + 1
        if pos < len(target_tokens):
            result.append(target_tokens[pos])

    accepted_draft = max(0, len(result) - 1)
    return result, accepted_draft
```

Explanation:

- This is a very direct simulation of the `sample_and_accept_n` control flow:
  - accept matching prefix
  - break on first mismatch
  - if fully matched, append one extra target token
- The target stream is pre-written in `state.json`, not generated by a model.

Implementation meaning:

- This is the simplest possible semantics demo for longest-prefix acceptance.
- It captures the control flow idea of upstream `llama.cpp`, but not the runtime implementation.

### 4.4 Shared State Initialization

File:

- `reference/spec-split-demo-project/init_demo.py`

Core code:

```python
target_text = "I like distributed speculative decoding where draft and verify are split."
target_tokens = ["<BOS>"] + target_text.split(" ")

state = {
    "round": 0,
    "accepted_pos": 0,
    "target_tokens": target_tokens,
    "done": False,
}
```

Explanation:

- The "target model" is just a fixed token list in shared state.
- The verifier advances a pointer through that list.

Implementation meaning:

- This confirms the project is intentionally a logic demo, not an inference runtime.

## 5. Direct Comparison

### 5.1 Which one is closest to upstream `llama.cpp`?

Closest:

- the current project `llama_cpp_spec_native`

Reason:

- token-native draft ids
- persistent native verifier helper
- `common_sampler_sample_and_accept_n(...)`
- step-local tail trimming
- active work toward lighter draft continuity

Not closest:

- `Android-Speculative-Inference` demo
- `spec-split-demo-project`

Reason:

- replay-style draft session
- codepoint-compatible draft ids
- Python verifier orchestration as the main runtime boundary
- or, in the split demo case, no model runtime at all

### 5.2 Why the old demos still matter

The older demos are still useful because they show very clean architectural splits:

- Android proposes
- desktop verifies
- session protocol is easy to inspect

or even more minimally:

- draft worker proposes
- verify worker decides
- shared state advances round by round

That is good for protocol clarity and debugging.

But it should not be mistaken for the same implementation class as upstream `llama.cpp`.

### 5.3 Where `spec-split-demo-project` fits

The split demo is best understood as:

- control-flow illustration
- protocol separation illustration
- not a runtime design reference

Compared with the Android demo:

- it is even simpler
- it is even further from real model inference
- but it exposes the acceptance semantics more directly

### 5.4 Why the current project still performs worse than upstream

Even after moving closer to upstream semantics, the current project still carries extra costs that upstream does not:

- Android device constraints
- cross-device request/response orchestration
- JNI boundary overhead
- draft-session persistence overhead
- UI/debug/summary work around the hot path

So the current project is:

- structurally closer to upstream
- operationally heavier than upstream

## 6. Bottom Line

The four implementations represent four different levels of ambition:

1. `Android-Speculative-Inference` demo
   - protocol-first
   - split-architecture demo
   - replay-heavy and codepoint-oriented

2. `spec-split-demo-project`
   - control-flow-first
   - split-process semantics demo
   - no real model runtime at all

3. upstream `llama.cpp`
   - runtime-first
   - persistent-state speculative decoding
   - token-native and performance-oriented

4. current project `llama_cpp_spec_native`
   - parity-first
   - trying to reproduce upstream runtime semantics across a cross-device architecture
   - therefore much closer to upstream in design, but still heavier in practice
