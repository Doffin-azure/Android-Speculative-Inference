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
