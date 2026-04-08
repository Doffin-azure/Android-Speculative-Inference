# `llama_cpp_spec_native` Gap Checklist

## Purpose

This checklist tracks the implementation gaps between the current cross-device `llama_cpp_spec_native` lane and the upstream `llama.cpp` speculative runtime model.

It is intentionally code-focused.

## Confirmed Current Gaps

### 1. Android draft continuity

Status before the current continuity work:

- `startDraftSession(...)` created a Kotlin-side session shell, but every real-token draft fetch still rebuilt native state from `system + user + acceptedText`.
- `draftNextRealTokenIds(...)` and `draftRealTokenTreeProposal(...)` both called `resetDraftRuntime(...)`.
- native `resetDraftContext(...)` replayed the full prefix through `process_prompt_text(...)` and `process_assistant_prefill_text(...)`.

Main code:

- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

Target parity:

- keep one committed draft state
- restore that committed state before speculative expansion
- commit only accepted verifier tokens
- do not rebuild from full assistant text for every step

Current note after the first continuity pass:

- text replay is no longer the dominant real-token fast-path mechanism
- but draft-side persistence must still stay lightweight enough to avoid replacing replay cost with an equally heavy whole-state round-trip
- the native draft runtime now also skips redundant restore calls when the current session is already live at its committed state
- the native draft runtime now also attempts an in-place rollback-to-committed path before falling back to sequence-state restore
- the remaining continuity gap is therefore no longer "always restore before every draft fetch"; it is that the project still relies on committed snapshot round-trips instead of upstream-style in-place KV reuse and trim

### 1b. Android real-token draft candidate extraction

Confirmed hotspot:

- the real-token draft fast path previously called `top_candidates_from_current_logits(...)` for every drafted token
- that function scanned the full vocabulary and computed a softmax denominator across the full vocabulary

Main code:

- `lib/src/main/cpp/ai_chat.cpp`

Target parity:

- use the sampler's existing candidate buffer
- stay close to upstream `common_sampler_sample(...) + common_sampler_get_candidates(...)`
- avoid full-vocabulary work on every draft token unless a tree/probe path explicitly needs it

### 2. Desktop verifier continuity

Status before the current continuity work:

- `verify_draft_batch` rebuilt sampler state every round
- `restore_anchor_state(...)` cleared the full context and replayed the anchor prefix
- `rebuild_session_anchor(...)` detokenized accepted tokens back to text, rebuilt the replay prompt, then re-tokenized it

Main code:

- `tools/desktop_target_runtime.cpp`

Target parity:

- keep one committed verifier context alive for the whole target session
- verify the next draft slice on top of the committed anchor
- trim only the temporary verifier tail after each step
- keep `rebuild_session_anchor(...)` as fallback only

### 3. Sampler lifecycle reuse

Status before the current continuity work:

- helper `verify_draft_batch` called `common_sampler_free(...)` + `common_sampler_init(...)` every step

Main code:

- `tools/desktop_target_runtime.cpp`

Target parity:

- keep one sampler per session
- only rebuild when sampling config actually changes
- otherwise reuse session sampler state

### 4. Step economics

Current benchmark defaults:

- `SPECULATIVE_TEST_MAX_STEPS = 128`
- `SPECULATIVE_TEST_MAX_DRAFT_TOKENS = 16`

Main code:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

Gap:

- upstream speculative logic explicitly avoids very short draft slices
- the project benchmark path still needs an explicit `n_min`-style guard

### 5. Client-side render and debug overhead

Current cost sources:

- per-step token rendering for debug text
- detailed step trace assembly and summary rendering

Main code:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

Gap:

- these are useful for debugging, but they are not part of the core speculative algorithm and can distort end-to-end wall-clock measurements

Current note:

- the real-token speculative fast path no longer renders `proposedText` on every step for request submission
- final committed text rendering and debug summaries still remain as separate overhead sources
- the hot-path protocol for `llama_cpp_spec_native` no longer includes `proposedText` or `draftTree`; older lanes still keep those payloads for regression and tree-aware verification
- the new experimental `llama_cpp_spec_split` lane now goes one step further and locks helper verification onto a dedicated split command that does not accept helper-side accepted-token reinjection on the hot path

## Current Benchmark Template

Use one prompt across all three modes:

1. `LOCAL`
2. `REMOTE`
3. `SPECULATIVE`

Prompt characteristics:

- long output
- low randomness
- stable structure
- engineering or technical explanation style

Record these timings:

- total run ms
- start session ms
- local draft open ms
- total draft fetch ms
- total remote propose ms
- total local apply ms
- close session ms

## Current Working Conclusion

The strongest current bottleneck is not acceptance logic. It is insufficient runtime continuity.

The most important parity work therefore remains:

1. Android committed-state draft runtime
2. desktop persistent target session
3. sampler reuse
4. benchmark-oriented step economics
