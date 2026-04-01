# 2026-04-01 EAGLE Alignment Gap And Exact-Lane Plan

This note records the first point where the project stopped treating `llama_true_tree_pq_tokens` as the final design.

## What Was Confirmed

- `llama_true_tree_pq_tokens` successfully validated a real-token speculative lane end to end.
- That lane now proves Android draft ids, draft-tree metadata, and desktop target ids can be compared in the same real-token space.
- It also proves the project can run first-pass per-token `p/q` acceptance on real token ids.

## What Was Also Confirmed

That experimental lane still does **not** preserve the verifier model's output distribution the way EAGLE does.

The remaining gaps are:

- target `p(x)` still comes from observed top-k slices instead of full logits
- correction still uses observed-top-k residual instead of full-vocab `max(p-q, 0)`
- follow-up continuation still uses observed top-k instead of the exact target distribution
- the verifier still depends on Python coordination instead of a native persistent target runtime helper
- Android draft and desktop target still need stricter exact prefix-state alignment

## New Mainline Decision

The project now freezes three verifier lanes with separate roles:

- `llama_true_tree`
  Regression baseline
- `llama_true_tree_pq_tokens`
  Experimental approximation baseline
- `llama_eagle_aligned`
  New correctness lane for output-preserving work

The new correctness lane must:

- use unified real token ids end to end
- use a native desktop target runtime helper as verifier truth
- read exact full-logits `p(x | prefix_i)`
- read exact branch-conditioned `q(x | prefix_i)` from Android `draftPathSteps`
- run exact `min(1, p/q)` acceptance
- sample exact residual correction `max(p-q, 0)`
- fail closed if the exact helper is unavailable

## Confirmed Local llama.cpp APIs For The Exact Lane

The local `llama.cpp` checkout already exposes the native APIs needed for the exact helper design:

- tokenization / rendering
  - `llama_tokenize`
  - `llama_detokenize`
  - `llama_token_to_piece`
  - `llama_vocab_get_text`
- full-logits access
  - `llama_get_logits_ith`
- sequence / runtime state
  - `llama_memory_seq_cp`
  - `llama_memory_seq_keep`
  - `llama_memory_seq_rm`
  - `llama_state_seq_get_data`
  - `llama_state_seq_set_data`
- sampler path for exact target / residual sampling
  - `llama_sampler_chain_init`
  - `llama_sampler_apply`
  - `llama_sampler_sample`
  - `llama_get_sampled_candidates_ith`
  - `llama_get_sampled_probs_ith`

## First Code Node After This Decision

The first exact-lane code node includes:

- a new verifier mode name: `llama_eagle_aligned`
- explicit `draftPathSteps` on the Android real-token draft payload
- a new `tools/desktop_target_runtime.cpp` helper skeleton
- server-side fail-closed wiring so the exact lane cannot silently reuse the approximation path
