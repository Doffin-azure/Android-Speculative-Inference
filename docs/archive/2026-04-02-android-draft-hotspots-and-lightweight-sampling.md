# 2026-04-02 Android Draft Hotspots And Lightweight Sampling

## Why This Node Exists

After the first continuity-focused `llama_cpp_spec_native` optimization pass, the draft side still showed severe wall-clock degradation compared with:

- ordinary Android local generation
- ordinary phone-to-desktop remote generation

This node records the confirmed reasons and the next concrete optimization step.

## Confirmed Root Causes

### 1. Real-token draft sampling was more expensive than ordinary local generation

The ordinary local generation path samples tokens through the normal sampler path:

- `common_sampler_sample(...)`

The real-token draft path did not use that directly.

Instead, it called:

- `top_candidates_from_current_logits(...)`

That function scanned the full vocabulary, partially sorted candidate ids, and computed a softmax denominator across the full vocabulary before returning the best token and its probability.

This meant draft generation was paying a much heavier per-token logits post-processing cost than ordinary generation.

### 2. Persistent draft continuity still used heavy state round-trips

The first continuity pass replaced full text replay with native state persistence, but the initial implementation still used:

- `llama_state_get_data(...)`
- `llama_state_set_data(...)`

on the whole runtime state.

That removed prompt replay, but it still left a large full-state save/restore cost on every speculative draft step.

### 3. Speculative draft still carries algorithm-external coordination cost

The speculative loop still performs work that ordinary local generation does not have to do:

- token rendering for request/debug text
- remote `propose` round-trip
- local apply/commit after verification

So even after draft-side improvements, speculative must still save enough target-side work to pay for those extra coordination costs.

## What Changed In This Node

### Lightweight real-token draft candidate selection

The draft path now uses the sampler's existing candidate buffer instead of recomputing top-k and softmax from raw logits for every token.

This moves Android draft token selection closer to upstream `llama.cpp` speculative draft behavior.

### Sequence-state persistence instead of whole-state persistence

The persistent draft-session implementation now stores and restores sequence state through:

- `llama_state_seq_get_data(...)`
- `llama_state_seq_set_data(...)`

instead of the heavier whole-context state round-trip.

This keeps the committed-state design while reducing the persistence cost.

### Skip real-token `proposedText` rendering on the hot path

The Python service verifies the `llama_cpp_spec_native` lane from `proposedTokenIds`.

The Android client was still detokenizing `proposedTokens` into `proposedText` on every speculative step even though that field was not part of the native helper's verifier decision.

The client fast path now skips that per-step render for the real-token speculative lane and keeps only a lightweight trace placeholder for the UI summary.

### Skip per-step real-token `acceptedText` detokenize during local apply

The local real-token apply path was still detokenizing newly committed tokens on every verifier step only to update the draft-session handle text field.

That text was not required for the native committed-state semantics of the `llama_cpp_spec_native` lane.

The local fast path now keeps real-token draft session state token-first during apply and leaves committed text rendering to later, on-demand paths.

## Scope Note

This node does not claim that all draft-side degradation is solved.

It claims only that two confirmed hotspots were directly optimized:

1. full-vocabulary draft candidate extraction
2. whole-state save/restore for committed draft sessions
3. unnecessary per-step real-token request rendering on the Android client
4. unnecessary per-step real-token accepted-text rendering during local apply

## Files

- `lib/src/main/cpp/ai_chat.cpp`
- `docs/project/llama-cpp-spec-native-gap-checklist.md`
- `docs/project/current-status.md`
