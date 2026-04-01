# Speculative Core Code Explanation

## Purpose

This document collects the core code behind the current speculative implementation.

It is not a changelog.

It exists so that future work can quickly answer:

- which code is the real implementation core
- where the current desktop verifier truth comes from
- how Android currently drives the speculative loop
- what must be updated when a new core feature lands

## Documentation Rule

For every future core feature node:

1. update this document or add a clearly linked follow-up code explanation
2. include the key code snippet
3. explain what that code actually does
4. explain why that snippet is the implementation core

## Current Scope

The current code below covers the present speculative scheme:

1. desktop target-session state
2. desktop true-verifier next-token / chunk call
3. desktop true-verifier comparison loop
4. desktop `propose` mode dispatch
5. Android speculative multi-step regression loop
6. Android draft-session interface boundary
7. Android first local draft-session runtime
8. Desktop first tree-shaped true verifier
9. desktop piece-aware candidate projection
10. draft-tree-aware piece-prefix acceptance
11. first experimental `p/q` gate and the token-space boundary
12. Android parallel real-token draft API skeleton
13. experimental real-token verifier-mode wiring
14. experimental unified-token `token_pq` acceptance
15. observed-top-k residual correction on the experimental lane

## 1. Desktop Target-Session State

File:

- `tools/desktop_inference_service.py`

Core code:

```python
@dataclass
class TargetSessionState:
    target_session_id: str
    speculative_session_id: str
    request_id: str
    verifier_mode: str
    verifier_stage: str
    target_model: str
    system_prompt: str
    user_prompt: str
    accepted_text: str
    target_preview_text: str
    last_replay_prompt: str
    last_target_text_delta: str
    target_token_ids: list[int]
    accepted_token_count: int
    mismatch_count: int
    true_verifier_call_count: int
    last_true_expected_token_id: int
    last_true_expected_token_text: str
    true_prefix_cache: dict[str, str]
    true_runtime_backend: str
    llama_server_slot_id: int
    last_true_chunk_start: int
    last_true_chunk_consumed: int
    true_cache_hit_streak: int
    true_fetch_streak: int
    created_at_ms: int
    updated_at_ms: int
```

Explanation:

- This is the first place where desktop verifier state is separated from the outer speculative session shell.
- `accepted_text` is the current accepted assistant prefix.
- `target_preview_text` and `last_replay_prompt` hold current verifier-side debugging state.
- `target_token_ids`, `accepted_token_count`, and `mismatch_count` track verifier progress.
- `true_runtime_backend` and `llama_server_slot_id` now record whether the true verifier is running through standalone `llama-cli` replay or through a fixed `llama-server` slot.
- `last_true_chunk_start`, `last_true_chunk_consumed`, `true_cache_hit_streak`, and `true_fetch_streak` now expose verifier continuity state that was previously only implicit.

Why this is core:

- The later true verifier cannot be built cleanly if verifier state only lives inside the HTTP/session wrapper.
- This object is the state anchor for the desktop verifier.

## 2. Desktop True Verifier Next-Token / Chunk Call

File:

- `tools/desktop_inference_service.py`

Core code:

```python
def run_generation_from_server_completion(
    config: ServiceConfig,
    *,
    request_id: str,
    model: str,
    full_prompt: str,
    max_tokens: int,
    temperature: float,
    top_p: float,
    slot_id: int,
    cache_prompt: bool,
) -> dict[str, Any]:
    response = request_json(
        "POST",
        f"{config.llama_server_base_url}/completion",
        {
            "prompt": full_prompt,
            "n_predict": max(1, max_tokens),
            "temperature": temperature,
            "top_p": top_p,
            "cache_prompt": cache_prompt,
            "id_slot": slot_id,
            "return_tokens": True,
            "stream": False,
            "n_keep": -1,
        },
    )
    return {
        "outputText": str(response.get("content") or ""),
        "backendLabel": "desktop-llama.cpp-server",
    }

def run_true_target_chunk_text(
    config: ServiceConfig,
    *,
    request_id: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    accepted_text: str,
    max_tokens: int,
    target_session: TargetSessionState | None = None,
) -> dict[str, Any]:
    replay_prompt = build_replay_prompt(system_prompt, user_prompt, accepted_text)
    if config.llama_server_base_url and target_session is not None and target_session.llama_server_slot_id >= 0:
        response = run_generation_from_server_completion(
            config,
            request_id=request_id,
            model=model,
            full_prompt=replay_prompt,
            max_tokens=max(1, max_tokens),
            temperature=0.0,
            top_p=1.0,
            slot_id=target_session.llama_server_slot_id,
            cache_prompt=True,
        )
        response.setdefault("debug", {})
        response["debug"]["runtimeBackend"] = "llama_server_slot"
        return response

    response = run_generation_from_full_prompt(...)
    response.setdefault("debug", {})
    response["debug"]["replayPrompt"] = replay_prompt
    response["debug"]["runtimeBackend"] = "llama_cli_replay"
    return response
```

Explanation:

- This is now the main runtime seam for the true verifier.
- It still rebuilds the prompt from the current accepted assistant prefix, but it can now fetch deterministic target continuation through two different runtimes:
  - standalone `llama-cli`
  - `llama-server` `/completion` with a fixed slot and prompt-cache reuse
- `temperature=0.0` and `top_p=1.0` keep the path deterministic so it behaves like a verifier, not like an ordinary sampling call.

Why this is core:

- Before this function family existed, verifier truth came from preview text or replay text proxies.
- After it was strengthened, desktop gained a true verifier that can now also route through a more persistent `llama-server` slot-backed runtime.

Current strengthening:

- true-mode refresh no longer performs a redundant prefetch call before verification
- the target session now records:
  - `true_verifier_call_count`
  - `last_true_expected_token_id`
  - `last_true_expected_token_text`
- the target session now also caches:
  - `true_prefix_cache`

## 3. Desktop True Verifier Comparison Loop

File:

- `tools/desktop_inference_service.py`

Core code:

```python
def compute_true_verifier_result(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    accepted_token_ids: list[int],
    accepted_token_count: int,
    proposed_token_ids: list[int],
    max_correction_tokens: int,
) -> VerifyComputation:
    accepted_step_token_ids: list[int] = []
    correction_token_ids: list[int] = []
    rejected_from_index = -1
    target_index = accepted_token_count
    working_prefix = target_session.accepted_text

    for index, proposed_token_id in enumerate(proposed_token_ids):
        next_response = run_true_target_next_text(
            config,
            request_id=f"{target_session.request_id}-true-step-{target_index + index}",
            model=target_session.target_model,
            system_prompt=target_session.system_prompt,
            user_prompt=target_session.user_prompt,
            accepted_text=working_prefix,
        )
        next_text = str(next_response.get("outputText") or "")
        expected_token_id = ord(next_text[0])

        if proposed_token_id == expected_token_id:
            accepted_step_token_ids.append(proposed_token_id)
            working_prefix += chr(proposed_token_id)
            continue

        rejected_from_index = index
        correction_token_ids = [expected_token_id][:max_correction_tokens]
        break

    return VerifyComputation(
        accepted_token_ids=accepted_step_token_ids,
        correction_token_ids=correction_token_ids,
        rejected_from_index=rejected_from_index,
        target_text_delta=token_ids_to_debug_text(accepted_step_token_ids + correction_token_ids),
        finish_reason="",
        target_index_before_step=target_index,
        target_remaining_count=0,
        target_preview_debug=target_session.target_preview_text[:16],
    )
```

Explanation:

- This is the actual verification loop.
- It compares Android-proposed tokens against the target model's next token, one step at a time.
- Matching tokens are appended to the accepted prefix.
- The first mismatch returns one correction token.
- Each real verifier step now also records the latest expected token and increments the true-verifier call counter inside the target session.
- If the same accepted prefix is checked again, the verifier can now reuse the cached next-token observation instead of calling the target model again.

## 14. Experimental Unified-Token `token_pq` Acceptance

File:

- `tools/desktop_inference_service.py`

Core code:

```python
def compute_true_tree_pq_token_verifier_result(...):
    for depth, proposed_token_id in enumerate(proposed_token_ids):
        top_candidates = fetch_target_top_candidates(...)
        target_prob_by_token = {
            candidate.token_ids[0]: candidate.probability
            for candidate in top_candidates
            if candidate.token_ids
        }
        draft_prob_by_token = {
            node.token_id: node.probability
            for node in draft_tree.nodes
            if node.depth == depth
        }

        target_probability = target_prob_by_token.get(proposed_token_id, 0.0)
        draft_probability = draft_prob_by_token.get(proposed_token_id, 0.0)
        acceptance_probability = min(1.0, target_probability / draft_probability)
        pq_accepted = deterministic_probability_draw(...) <= acceptance_probability

        if pq_accepted:
            accepted_step_token_ids.append(proposed_token_id)
            working_prefix += render_token_ids_for_verifier(...)
            continue
        ...
```

Explanation:

- This is the first verifier path that runs accepted/rejected logic directly on real token ids instead of codepoint-compatible ids.
- `p(x)` comes from the target-side top-k token ids returned by `llama-server`.
- `q(x)` comes from the Android real-token draft tree at the same depth.
- `accP = min(1, p/q)` is applied per proposal token on that shared real-token space.

Why this is core:

- This is the first implementation node that actually crosses the project’s token-space boundary and proves Android draft ids and desktop target ids can be compared directly.
- The successful end-to-end run with:
  - `verifierMode=llama_true_tree_pq_tokens`
  - `tokenMode=real_token`
  - `acceptanceMode=token_pq`
  showed that the experimental lane can now accept and reject on unified real token ids instead of on debug-only text projections.

## 15. Observed-Top-K Residual Correction

File:

- `tools/desktop_inference_service.py`

Core code:

```python
def choose_residual_token_id(
    target_prob_by_token: dict[int, float],
    draft_prob_by_token: dict[int, float],
    *,
    request_id: str,
    target_index: int,
    depth: int,
    working_prefix: str,
) -> tuple[int, float, float]:
    residual_items = []
    for token_id, target_prob in target_prob_by_token.items():
        residual = max(0.0, target_prob - draft_prob_by_token.get(token_id, 0.0))
        if residual > 0.0:
            residual_items.append((token_id, residual))
    ...
```

Explanation:

- On the experimental `token_pq` lane, rejection no longer jumps straight to target top-1 correction.
- The verifier now first builds an observed residual `max(p-q, 0)` over the currently available target top-k token ids.
- If that residual slice is non-empty, correction is sampled from the residual distribution with the same deterministic draw family used elsewhere.
- Only if the observed residual is empty does the verifier fall back to target best-token correction.

Why this is core:

- This is the first correction-side move from heuristic "best token" correction toward a paper-style residual correction rule.
- It is still only an approximation because the residual is computed over the observed top-k slice, not over full-vocabulary logits, but it establishes the right algorithmic seam for the next verifier-strengthening node.
- The cache is now session-wide instead of single-entry, so multiple previously seen prefixes can be reused inside the same desktop target session.
- The true verifier now also uses a dedicated helper to read the latest cache entry, so debug output no longer duplicates cache-selection logic in multiple response builders.
- The true verifier now fetches a small continuation chunk for the current prefix and compares the proposal against that chunk, so one verifier call can now accept multiple tokens before returning a correction.
- The true verifier can now fetch that chunk through a fixed `llama-server` slot, and the target session tracks where the latest chunk started and how many committed tokens it consumed.

Why this is core:

- This is where accepted-prefix and correction-token semantics stop being a stub and start depending on the target model.

## 4. Desktop `propose` Mode Dispatch

File:

- `tools/desktop_inference_service.py`

Core code:

```python
if session.verifier_mode == "llama_true_step":
    computation = compute_true_verifier_result(
        server.config,
        target_session,
        accepted_token_ids=session.accepted_token_ids,
        accepted_token_count=session.accepted_token_count,
        proposed_token_ids=proposed_token_ids,
        max_correction_tokens=max_correction_tokens,
    )
else:
    computation = compute_proxy_verifier_result(
        target_session,
        accepted_token_ids=session.accepted_token_ids,
        accepted_token_count=session.accepted_token_count,
        proposed_token_ids=proposed_token_ids,
        max_correction_tokens=max_correction_tokens,
    )
```

Explanation:

- This is the switch that keeps the protocol stable while changing the verifier engine underneath.
- Proxy modes still work for regression.
- `llama_true_step` now activates the first true-target path.

Why this is core:

- This dispatch point is the clean seam between protocol lifecycle and verifier implementation.
- Future verifier upgrades should happen here, not by rewriting the whole endpoint.

## 6. Android Draft-Session Interface Boundary

Files:

- `lib/src/main/java/com/example/myapplication/llama/InferenceEngine.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlm.kt`

Core code:

```kotlin
data class DraftSessionHandle(
    val sessionId: String,
    val runtimeLabel: String,
    val acceptedText: String = "",
    val acceptedTokenCount: Int = 0
)

fun supportsDraftSession(): Boolean = false

suspend fun startDraftSession(
    systemPrompt: String,
    userPrompt: String,
    predictLength: Int = DEFAULT_PREDICT_LENGTH
): DraftSessionHandle {
    throw UnsupportedOperationException("Draft session is not implemented by this engine.")
}

suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int>
suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle
suspend fun closeDraftSession(sessionId: String)
```

Explanation:

- This is the first explicit boundary for true draft work on Android.
- The current implementation still returns `unsupported`, which is intentional: the runtime contract is now fixed before the native path is changed.
- `DraftSessionHandle` is the smallest shared state shape that can later connect Kotlin UI code to a native speculative-draft session.

Why this is core:

- Before this boundary existed, the codebase only had one-shot `generate(...)` semantics.
- Real speculative draft work needs `start / draft / apply / close` semantics, and this is the first code-level seam for that transition.

## 7. Android First Local Draft-Session Runtime

Files:

- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

Core code:

```kotlin
override suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
    require(maxTokens > 0) { "maxTokens must be > 0." }
    resetDraftRuntime(runtime)
    generateDraftTokenIds(maxTokens).toList()
}

override suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")

    val appendedText = codePointIdsToString(tokenIds)
    val updatedRuntime = runtime.copy(acceptedText = runtime.acceptedText + appendedText)
    resetDraftRuntime(updatedRuntime)
    draftSessions[sessionId] = updatedRuntime
    DraftSessionHandle(
        sessionId = updatedRuntime.sessionId,
        runtimeLabel = "ai-chat draft session",
        acceptedText = updatedRuntime.acceptedText,
        acceptedTokenCount = updatedRuntime.acceptedText.codePointCount(0, updatedRuntime.acceptedText.length)
    )
}
```

```cpp
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_resetDraftContext(...) {
    reset_long_term_states();
    reset_short_term_states();

    const int system_result = process_prompt_text(system, ROLE_SYSTEM, true);
    const int user_result = process_prompt_text(user, ROLE_USER, false, true);
    const int assistant_result = process_prompt_text(assistant, ROLE_ASSISTANT, false);

    stop_generation_position = current_position + std::max(1, (int) predict_length);
    return 0;
}

JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftTokenIds(...) {
    const auto new_token_id = common_sampler_sample(g_sampler, g_context, -1);
    common_sampler_accept(g_sampler, new_token_id, true);
    ...
    auto new_token_chars = common_token_to_piece(g_context, new_token_id);
    cached_token_chars += new_token_chars;
    ...
    draft_ids.push_back((jint) codepoint);
}
```

```kotlin
val baseTokens = if (activeLocalDraftSessionId != null) {
    localLlm.draftNextTokenIds(
        sessionId = activeLocalDraftSessionId,
        maxTokens = SPECULATIVE_STUB_MAX_DRAFT_TOKENS
    )
} else {
    buildStubProposalSlice(
        seedTokens = draftSeedTokens,
        committedCount = committedTokenIds.size
    )
}
```

Explanation:

- Android now has a first real local draft-session runtime instead of only an `unsupported` boundary.
- Kotlin stores the local draft-session metadata and rebuilds the native runtime from the current verified assistant prefix before each draft step.
- Native code samples from the real local model path and converts emitted UTF-8 text into codepoint ids so the current desktop verifier protocol can consume the result without a wire-format break.
- `applyVerifiedTokens(...)` advances the accepted assistant prefix, which means later draft steps are conditioned on what desktop actually accepted and corrected.
- `MainViewModel` now prefers this local draft session whenever the engine reports support, and only falls back to the old stub proposal path when the local draft runtime is unavailable.

Why this is core:

- This is the first point where Android speculative proposals can come from the local model runtime instead of only from a prompt-derived UI stub.
- It is not yet true libllama token-id drafting or rollback-capable speculative runtime, but it is the first real draft-runtime implementation node and the bridge we need before deeper EAGLE-style session work.

## 8. Desktop First Tree-Shaped True Verifier

File:

- `tools/desktop_inference_service.py`

Core code:

```python
def fetch_target_top_candidates(
    config: ServiceConfig,
    target_session: TargetSessionState,
    *,
    prefix_text: str,
    step_index: int,
    branch_factor: int,
) -> dict[str, Any]:
    response = run_generation_from_server_completion(
        config,
        request_id=f"{target_session.request_id}-true-tree-{step_index}",
        model=target_session.target_model,
        full_prompt=replay_prompt,
        max_tokens=1,
        temperature=0.0,
        top_p=1.0,
        slot_id=target_session.llama_server_slot_id,
        cache_prompt=True,
        n_probs=max(1, branch_factor),
        post_sampling_probs=True,
    )
```

```python
def build_true_tree_computation(...):
    for depth in range(total_depth):
        top_result = fetch_target_top_candidates(...)
        candidates = list(top_result.get("candidates") or [])
        best_candidate = candidates[0]
        best_token_id = int(best_candidate.get("tokenId", -1))
        best_path_token_ids.append(best_token_id)

        if depth < len(proposed_token_ids):
            if proposed_token_id == best_token_id:
                accepted_step_token_ids.append(best_token_id)
                working_prefix += chr(best_token_id)
                continue

            rejected_from_index = depth
            correction_token_ids = [best_token_id]
            working_prefix += chr(best_token_id)
            continue
```

```python
elif session.verifier_mode == "llama_true_tree":
    computation = compute_true_tree_verifier_result(
        server.config,
        target_session,
        accepted_token_ids=session.accepted_token_ids,
        accepted_token_count=session.accepted_token_count,
        proposed_token_ids=proposed_token_ids,
        max_correction_tokens=max_correction_tokens,
    )
```

Explanation:

- The verifier now has a new `llama_true_tree` mode that keeps the existing `proposedTokenIds` wire format but internally expands each target-side prefix into a shallow candidate tree.
- Candidate expansion comes from `llama-server` top-k probability results, not from Android sending a tree proposal.
- The first version scores a best path by target top-1 at each level and maps that tree result back into the current accepted/correction protocol.
- The returned debug payload now exposes tree visibility fields such as candidate count, branch factor, depth evaluated, best path token ids, and a compact tree summary string.

Why this is core:

- This is the first verifier node that moves beyond linear chunk comparison and starts approximating the “one target evaluation looks at multiple candidate continuations” idea behind EAGLE-style verification.
- It does so without breaking the current Android regression client or forcing an immediate protocol redesign.

## 9. Android First Dynamic Draft Tree Proposal

File:

- `lib/src/main/java/com/example/myapplication/llama/InferenceEngine.kt`
- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

Core code:

```kotlin
data class DraftTreeNode(
    val nodeIndex: Int,
    val tokenId: Int,
    val tokenText: String,
    val depth: Int,
    val parentNodeIndex: Int,
    val probability: Float,
    val logProbability: Float,
    val cumulativeLogProbability: Float
)

data class DraftTreeProposal(
    val sessionId: String,
    val rootAcceptedText: String,
    val bestPathTokenIds: List<Int>,
    val bestPathNodeIndices: List<Int>,
    val bestPathText: String,
    val branchFactor: Int,
    val depthEvaluated: Int,
    val nodeCount: Int,
    val nodes: List<DraftTreeNode>
)
```

```kotlin
override suspend fun draftTreeProposal(
    sessionId: String,
    maxDepth: Int,
    branchFactor: Int
): DraftTreeProposal = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
    resetDraftRuntime(runtime)
    parseDraftTreeProposalJson(
        sessionId = sessionId,
        rootAcceptedText = runtime.acceptedText,
        jsonText = generateDraftTreeJson(maxDepth, branchFactor)
    )
}
```

```cpp
static std::vector<draft_tree_candidate> top_candidates_from_current_logits(int branch_factor) {
    const float *logits = llama_get_logits(g_context);
    ...
    std::partial_sort(...);
    ...
    candidates.push_back({
        token_id,
        common_token_to_piece(g_context, token_id),
        probability,
        log_probability,
    });
}

JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftTreeJson(...) {
    const auto candidates = top_candidates_from_current_logits(safe_branch_factor);
    const auto &best_candidate = candidates.front();
    common_sampler_accept(g_sampler, best_candidate.token_id, true);
    ...
}
```

```kotlin
if (startResponse.verifierMode == "llama_true_tree" && localDraftTreeSupported) {
    val treeProposal = localLlm.draftTreeProposal(
        sessionId = activeLocalDraftSessionId,
        maxDepth = SPECULATIVE_STUB_MAX_DRAFT_TOKENS,
        branchFactor = 3
    )
    treeProposal.bestPathTokenIds.take(SPECULATIVE_STUB_MAX_DRAFT_TOKENS)
}
```

Explanation:

- Android draft sessions can now return a first dynamic tree proposal instead of only a flat draft token slice.
- Native code reads the current next-step logits from `g_context`, derives top-k candidates with probabilities, and can now expand multiple shallow branches by saving/restoring runtime state and replaying the last token after restore.
- The current tree is still intentionally lightweight: it keeps the existing codepoint-compatible wire format and does not do KV-copy parallelism, but it no longer collapses everything into a single top-1 rollout.
- `MainViewModel` can now prefer this local tree proposal when desktop is running `llama_true_tree`, while still falling back to the older linear draft path when the tree runtime is unavailable.

Why this is core:

- This is the first point where Android can produce probability-bearing speculative draft structure instead of only a linear token list.
- It is the first concrete Android-side step toward an EAGLE-inspired draft producer while preserving the current cross-device protocol.

## 10. Android Branch-Expanded Draft Tree

File:

- `lib/src/main/cpp/ai_chat.cpp`

Core code:

```cpp
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
    llama_state_set_data(g_context, snapshot.state_data.data(), snapshot.state_data.size());
    ...
    return rebuild_logits_cursor_from_snapshot(snapshot.host_snapshot);
}
```

```cpp
for (const auto &branch : active_branches) {
    restore_runtime_branch_snapshot(branch.snapshot);
    const auto candidates = top_candidates_from_current_logits(safe_branch_factor);

    for (const auto &candidate : candidates) {
        restore_runtime_branch_snapshot(branch.snapshot);
        advance_runtime_with_token(candidate.token_id, candidate.token_text);

        draft_tree_branch child_branch {
                capture_runtime_branch_snapshot(),
                node_index,
                depth + 1,
                branch.cumulative_log_probability + candidate.log_probability,
                branch.path_text + candidate.token_text,
                branch.path_ids
        };
        append_utf8_codepoints(candidate.token_text, child_branch.path_ids);
        ...
    }
}
```

Explanation:

- This is the first Android draft-tree implementation that actually explores multiple local branches instead of only following the top-1 token at every layer.
- The branch expansion is sequential, not parallel KV-copy branching, but it already uses real runtime state snapshots and the verified restore+replay rule from the probe demo.
- The returned tree now also exposes explicit node identities and cumulative branch scores, which is the first real branch-object skeleton for the Android draft runtime.

## 11. Remote Verifier Consumes Android Draft Tree

Files:

- `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `tools/desktop_inference_service.py`

Core code:

```kotlin
data class SpeculativeProposeRequest(
    val sessionId: String,
    val draftStep: Int,
    val proposedTokenIds: List<Int>,
    val proposedText: String,
    val maxCorrectionTokens: Int = 1,
    val draftTree: DraftTreeProposal? = null
)
```

```kotlin
val proposeResponse = remoteClient.proposeDraft(
    baseUrl = baseUrl,
    request = SpeculativeProposeRequest(
        sessionId = startResponse.sessionId,
        draftStep = draftStep,
        proposedTokenIds = proposedTokens,
        proposedText = draftText,
        maxCorrectionTokens = 1,
        draftTree = localDraftTreeProposal
    )
)
```

```python
draft_tree = parse_optional_draft_tree_payload(payload.get("draftTree"))
...
tree = build_true_tree_computation(
    config,
    target_session,
    target_index=target_index,
    proposed_token_ids=proposed_token_ids,
    max_correction_tokens=max_correction_tokens,
    draft_tree=draft_tree,
)
```

Explanation:

- This is the first remote-verifier node where Android is no longer limited to sending only a linear token slice.
- `llama_true_tree` can now receive the local Android draft tree as optional metadata and use draft/target overlap at each depth when choosing the target-side best candidate.
- The protocol remains backward-compatible because the old `proposedTokenIds` path is still required and still works when `draftTree` is absent.

## 13. Desktop Piece-Aware Candidate Projection

Files:

- `tools/desktop_inference_service.py`

Core code:

```python
def common_prefix_length(left: Sequence[int], right: Sequence[int]) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index

def candidate_probability(candidate: dict[str, Any]) -> float:
    prob = float(candidate.get("prob", 0.0) or 0.0)
    if prob > 0.0:
        return prob
    logprob = candidate.get("logprob")
    if logprob is None:
        return 0.0
    return math.exp(float(logprob))
```

```python
token_ids = token_ids_from_text(token_text)
if token_ids:
    normalized_candidates.append(
        {
            "tokenId": int(token_ids[0]),
            "tokenIds": token_ids,
            "tokenText": token_text,
            "prob": prob,
            "logprob": logprob,
            "score": float(logprob if logprob is not None else math.log(max(prob, 1e-12))),
        }
    )
```

Explanation:

- The desktop verifier no longer treats a target candidate like only its first codepoint during comparison.
- It now preserves the whole candidate token-id sequence on the desktop side and centralizes probability normalization.
- This removed the earlier failure mode where many target token pieces with leading spaces collapsed into the same apparent token and forced the verifier toward space-heavy best paths.

## 14. Draft-Tree-Aware Piece-Prefix Acceptance

Files:

- `tools/desktop_inference_service.py`

Core code:

```python
proposal_match_len = common_prefix_length(remaining_proposal, candidate_token_ids)
draft_path_match_len = common_prefix_length(draft_best_suffix, candidate_token_ids)
draft_overlap = len(set(candidate_token_ids) & set(draft_layer_prob_by_token.keys()))

sort_key = (
    draft_path_match_len,
    1 if draft_best_token_id == candidate_token_ids[0] else 0,
    proposal_match_len,
    1 if candidate_token_ids and candidate_token_ids[0] in draft_layer_prob_by_token else 0,
    draft_overlap,
    candidate_probability(candidate),
)
```

```python
matched_count = common_prefix_length(remaining_proposal, best_candidate_token_ids)
accepted = remaining_proposal[:matched_count]
correction = best_candidate_token_ids[matched_count:matched_count + max_correction_tokens]
```

Explanation:

- This is the current best working verifier behavior.
- The desktop side uses Android draft-tree best-path alignment, overlap, and proposal-prefix agreement to choose a best target candidate.
- It then accepts the longest common prefix between the proposal remainder and that candidate sequence, and uses the remaining candidate suffix as correction.
- This is the path that first produced natural accepted text such as `I'm just` instead of repeated spaces.

## 15. Experimental `p/q` Gate And The Token-Space Boundary

Files:

- `tools/desktop_inference_service.py`

Core code:

```python
selected_target_prob = summed_first_token_probability(candidates, proposed_token_id)
selected_draft_prob = float(draft_prob_by_token.get(proposed_token_id, 0.0))

if selected_target_prob > 0.0 and selected_draft_prob > 0.0:
    acceptance_probability = min(1.0, selected_target_prob / selected_draft_prob)
    probability_draw = deterministic_probability_draw(
        target_session.request_id,
        target_index,
        depth,
        proposed_token_id,
    )
    pq_accepted = probability_draw <= acceptance_probability
```

Explanation:

- This first experimental gate exposes real `p`, `q`, `accP`, `draw`, and `pqAccepted` diagnostics in live Android-to-desktop speculative runs.
- It also exposed the new hard boundary for the next implementation step: standard paper-style per-token `p/q` acceptance does not remain stable while Android still exports codepoint-compatible draft ids and the desktop target still reasons over token-piece candidates.
- In other words, this code showed that the next mainline is token-space unification, not more mixed-space acceptance tweaks.

## 16. Android Parallel Real-Token Draft API Skeleton

Files:

- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

Core code:

```kotlin
private external fun generateDraftRealTokenIds(maxTokens: Int): IntArray
private external fun generateDraftRealTokenTreeJson(maxDepth: Int, branchFactor: Int): String
private external fun renderTokenIds(tokenIds: IntArray): String

override suspend fun draftNextRealTokenIds(sessionId: String, maxTokens: Int): List<Int> = withContext(llamaDispatcher) {
    resetDraftRuntime(runtime)
    generateDraftRealTokenIds(maxTokens).toList()
}

override suspend fun applyVerifiedRealTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle = withContext(llamaDispatcher) {
    val updatedTokenIds = runtime.acceptedTokenIds + tokenIds.filter { it >= 0 }
    val updatedText = renderTokenIds(updatedTokenIds.toIntArray())
    ...
}
```

```cpp
JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftRealTokenIds(...) {
    ...
    draft_ids.push_back(static_cast<jint>(new_token_id));
}

JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftRealTokenTreeJson(...) {
    ...
    child_branch.path_ids.push_back(static_cast<int>(candidate.token_id));
}

static std::string detokenize_token_ids(const std::vector<int> &token_ids, const bool special = true) {
    ...
    return common_detokenize(g_context, tokens, special);
}
```

Explanation:

- The Android runtime now has a parallel experimental path that exposes real `llama_token` ids for draft-token generation and draft-tree generation.
- It also has a native detokenize helper so accepted real-token prefixes can be rendered back into assistant text without treating token ids like Unicode codepoints.
- The older legacy draft APIs were intentionally kept in place so the current speculative regression path can stay wire-compatible while the new token-space path is wired through protocol and desktop verification.

## 17. Experimental Real-Token Verifier-Mode Wiring

Files:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `tools/desktop_inference_service.py`

Core code:

```kotlin
val useRealTokenDraftPath = startResponse.verifierMode == "llama_true_tree_pq_tokens"

if ((startResponse.verifierMode == "llama_true_tree" || useRealTokenDraftPath) && localDraftTreeSupported) {
    val selectedTreeProposal = if (useRealTokenDraftPath) {
        localLlm.draftRealTokenTreeProposal(...)
    } else {
        localLlm.draftTreeProposal(...)
    }
    ...
}

val draftText = if (useRealTokenDraftPath && activeLocalDraftSessionId != null) {
    localLlm.renderTokenIds(proposedTokens)
} else {
    tokenIdsToReadableText(proposedTokens)
}
```

```python
elif session.verifier_mode in {"llama_true_tree", "llama_true_tree_pq_tokens"}:
    computation = compute_true_tree_verifier_result(...)
```

Explanation:

- The desktop service now recognizes a separate experimental verifier mode, `llama_true_tree_pq_tokens`.
- Android checks that verifier mode at session start and, only on that path, switches from the legacy draft APIs to the new real-token draft APIs.
- This creates a separate end-to-end experimental lane for unified-token work without replacing the current `llama_true_tree` regression baseline.

## 18. Experimental Desktop Token-Id Lookup Boundary

File:

- `tools/desktop_inference_service.py`

Core code:

```python
def tokenize_with_server(base_url: str, content: str, *, with_pieces: bool = False):
    response = request_json(
        "POST",
        f"{base_url}/tokenize",
        {
            "content": content,
            "add_special": False,
            "parse_special": True,
            "with_pieces": with_pieces,
        },
    )
    return response.get("tokens") if isinstance(response.get("tokens"), list) else []

def detokenize_with_server(base_url: str, token_ids: list[int]) -> str:
    response = request_json("POST", f"{base_url}/detokenize", {"tokens": token_ids})
    return str(response.get("content") or "")
```

```python
if is_real_token_verifier_mode(target_session.verifier_mode):
    raw_token_id = item.get("id", -1)
    token_id = int(raw_token_id) if isinstance(raw_token_id, (int, float)) else -1
    token_ids = [token_id] if token_id >= 0 else []
else:
    token_ids = token_ids_from_text(token_text) if token_text else []
    token_id = token_ids[0] if token_ids else -1
```

```python
session.accepted_text = render_token_ids_for_verifier(config, target_session, session.accepted_token_ids)
target_text_delta = render_token_ids_for_verifier(
    config,
    target_session,
    accepted_step_token_ids + correction_token_ids,
)
```

Explanation:

- The experimental verifier lane now has its first true token-native desktop boundary.
- On `llama_true_tree_pq_tokens`, target top-k candidates no longer get projected back into character ids; the verifier reads llama-server `completion_probabilities[*].id` directly and treats each target candidate as a real token id.
- The same lane now renders accepted/correction token ids through llama-server `/detokenize`, so replay prompts on that path no longer depend on debug-only character rendering.
- Fallback chunk tokenization on that path can also use llama-server `/tokenize`, which removes another protocol-edge character bridge.
- The same helper layer now also drives internal prefix advancement, target-preview debug strings, and `lastTrueExpectedTokenText`, so the experimental lane no longer silently falls back to character rendering after token ids have already crossed the protocol boundary.

Why this is core:

- The previous real-token work only created a parallel Android API surface and verifier-mode switch.
- This code is the first place where the desktop verifier itself starts consuming and emitting real token ids at the boundary, which is the prerequisite before the inner tree computation can become fully token-native.

## 19. Experimental Token-Native `p/q` Acceptance Function

File:

- `tools/desktop_inference_service.py`

Core code:

```python
def compute_true_tree_pq_token_verifier_result(...):
    for depth, proposed_token_id in enumerate(proposed_token_ids):
        top_result = fetch_target_top_candidates(...)
        candidates = list(top_result.get("candidates") or [])
        target_best_candidate = max(candidates, key=candidate_probability)
        target_prob_by_token = {
            int(candidate.get("tokenId", -1)): candidate_probability(candidate)
            for candidate in candidates
            if int(candidate.get("tokenId", -1)) >= 0
        }
        selected_target_prob = float(target_prob_by_token.get(proposed_token_id, 0.0) or 0.0)
        selected_draft_prob = float(draft_prob_by_token.get(proposed_token_id, 0.0) or 0.0)
        if selected_draft_prob > 0.0:
            pq_acceptance_prob = min(1.0, selected_target_prob / selected_draft_prob)
            pq_draw = deterministic_probability_draw(...)
            pq_accepted = pq_draw <= pq_acceptance_prob
```

```python
        if pq_accepted:
            accepted_step_token_ids.append(proposed_token_id)
            working_prefix += render_token_ids_for_verifier(config, target_session, [proposed_token_id])
            continue

        rejected_from_index = depth
        correction_token_ids = [target_best_token_id][:max_correction_tokens]
        break
```

```python
    if rejected_from_index == -1 and max_correction_tokens > 0:
        followup_result = fetch_target_top_candidates(...)
        ...
        correction_token_ids = followup_token_ids[:max_correction_tokens]
```

Explanation:

- The experimental `llama_true_tree_pq_tokens` lane no longer reuses the old piece-prefix acceptance function.
- It now performs a dedicated per-token `p/q` acceptance step on real token ids, rejects at the first failed token, and when all proposal tokens for the step are accepted it appends one target follow-up token.
- This is the first verifier function in the project that is shaped primarily around the paper-style token-by-token acceptance loop instead of around a piece-prefix candidate comparison.
- The Android client now also records `tokenMode` and `acceptanceMode` from desktop debug fields, so runs on this lane are distinguishable from the older legacy verifier path in UI diagnostics and copied logs.
- The same experimental lane now also has an explicit fallback contract: if desktop does not receive a `real_token` draft tree, it falls back to piece-prefix acceptance and reports that through `acceptanceMode=fallback_piece_prefix`; if Android does not have a local real-token draft session, it logs the same kind of fallback on the client side.
- The response-status mapping now also treats "all draft tokens accepted plus one target follow-up token" as an accepted step on this lane, which keeps the experimental logs closer to standard speculative-decoding semantics.
- Rejection handling on this lane is now also closer to the paper direction: before falling back to target top-1 correction, the verifier computes an observed-top-k residual distribution `max(p-q, 0)` and chooses correction from that residual when it is available.

Why this is core:

- This is the first point where the experimental real-token lane stops being only a protocol and lookup skeleton and starts having a distinct acceptance algorithm of its own.
- It does not yet make the whole verifier fully final, but it is the necessary node between "real token ids exist" and "real token speculative acceptance actually runs end-to-end".

## 12. Android Draft Runtime Uses Assistant Prefill Continuation

Files:

- `lib/src/main/cpp/ai_chat.cpp`

Core code:

```cpp
static int process_assistant_prefill_text(const std::string &text) {
    auto tokens = common_tokenize(
            g_context,
            text,
            false,
            true);
    if (decode_tokens_in_batches(g_context, g_batch, tokens, current_position, true)) {
        return 2;
    }
    append_runtime_tokens(tokens);
    current_position += token_count;
    assistant_ss << text;
    return 0;
}
...
const int assistant_result = process_assistant_prefill_text(assistant);
```

Explanation:

- The draft runtime no longer re-wraps the already accepted assistant prefix as a full assistant chat message during `resetDraftContext(...)`.
- Instead, it first formats system/user up to the assistant generation point and then directly prefills the accepted assistant continuation tokens.
- This matches the `llama.cpp` server-side assistant-prefill idea more closely and avoids later draft-tree steps drifting into chat-template control tokens like `<|start_header_id|>`.

## 5. Android Speculative Multi-Step Regression Loop

File:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

Core code:

```kotlin
private const val SPECULATIVE_STUB_MAX_STEPS = 3
private const val SPECULATIVE_STUB_MAX_DRAFT_TOKENS = 4

private fun selectSpeculativeStubSeedText(
    prompt: String,
    verifierMode: String,
    targetPreviewText: String
): String {
    return if (verifierMode.startsWith("llama_") && targetPreviewText.isNotBlank()) {
        targetPreviewText
    } else {
        prompt.trim()
    }
}

private fun maybeMutateStubDraftTokens(tokenIds: List<Int>, draftStep: Int): List<Int> {
    if (!_speculativeForceMismatch.value || tokenIds.isEmpty()) {
        return tokenIds
    }

    return tokenIds.mapIndexed { index, tokenId ->
        if (draftStep == 1 && (index == 1 || (index == 0 && tokenIds.size == 1))) {
            tokenId + 1
        } else {
            tokenId
        }
    }
}
```

Explanation:

- Android still uses a stub draft client, not real local-model token drafting.
- It seeds the draft from the prompt or the desktop preview text.
- It can deliberately inject a mismatch on the first draft step for regression testing.

Why this is core:

- This is the current regression harness that keeps the desktop verifier testable from the phone without waiting for real Android draft-token production.

## Current Reading Order

When reading code for the current speculative path, use this order:

1. `tools/desktop_inference_service.py`
2. `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
3. `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`

## Current Limitation

The current first true verifier is real in the sense that it asks the target model for the next token.

It is still not final because:

- it replays prompt state through `llama-cli`
- it does not yet hold a persistent in-memory target runtime session
- Android still sends stub draft tokens instead of real local-model draft tokens
