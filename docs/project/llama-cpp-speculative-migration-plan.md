# Llama.cpp Speculative Migration Plan

## Purpose

This document records how the project now maps `llama.cpp`'s currently implemented speculative decoding flow onto the existing Android draft + desktop verify architecture.

It is intentionally about the **current llama.cpp speculative scheme**, not EAGLE.

## Llama.cpp Current Implementation Shape

The upstream control flow lives primarily in:

- `reference/llama.cpp-upstream/common/speculative.cpp`
- `reference/llama.cpp-upstream/common/sampling.cpp`
- `reference/llama.cpp-upstream/tools/server/server-context.cpp`
- `reference/llama.cpp-upstream/examples/speculative-simple/speculative-simple.cpp`

The currently relevant behavior is:

1. a draft producer proposes a linear token slice
2. the target runtime batches:
   - the last accepted token
   - the drafted token slice
3. the target sampler checks the drafted sequence position by position
4. the target accepts the longest matching draft prefix
5. when all draft tokens match, the target appends one follow-up token
6. any uncommitted drafted tail is discarded

This is the behavior implemented by `common_sampler_sample_and_accept_n(...)`.

## Migration Decision

The project now adds a separate verifier lane:

- `llama_cpp_spec_native`

This lane is deliberately distinct from:

- `llama_true_tree`
- `llama_true_tree_pq_tokens`
- `llama_eagle_aligned`

Its role is:

- keep Android as the real-token draft producer
- move desktop verification into a native helper
- reproduce llama.cpp's current draft/verify/accept/rollback semantics

## Project Mapping

### Android

- Android remains responsible for producing `real_token` drafts.
- `llama_cpp_spec_native` requires an active local real-token draft session.
- This lane does not require `draftTree` or `draftPathSteps`.
- Android now treats this lane as fail-closed if the real-token draft session is unavailable.
- The JNI draft path now follows the same broad draft policy as upstream llama.cpp's current speculative lane:
  - use a small top-k draft candidate window
  - emit real token ids
  - stop extending the draft once the best-token probability falls below the draft confidence threshold

### Desktop Python Service

- `tools/desktop_inference_service.py` now treats `llama_cpp_spec_native` as a helper-backed verifier lane.
- Python remains responsible for:
  - session lifecycle
  - helper process orchestration
  - HTTP request / response shaping
  - debug forwarding
- Python no longer performs the verifier algorithm for this lane.

### Native Helper

- `tools/desktop_target_runtime.cpp` now implements a real helper command set:
  - `load_model`
  - `start_session`
  - `verify_draft_batch`
  - `render_tokens`
  - `tokenize_text`
  - `close_session`
  - `shutdown`
- The helper uses the target model's tokenizer, sampler, batch decode path, and session state directly.
- The helper returns:
  - accepted draft prefix
  - one target mismatch or follow-up token
  - detokenized `targetTextDelta`
  - detokenized `acceptedTextAfterStep`

### Response Semantics

- On this lane, the wire field `correctionTokenIds` is still reused for compatibility with the existing protocol.
- Its meaning depends on the verifier outcome:
  - if `rejectedFromIndex >= 0`, it is the first target mismatch token after the accepted prefix
  - if `rejectedFromIndex == -1`, it is the single target follow-up token appended after a fully accepted draft slice
- In other words, `correctionTokenIds` is a transport-compatible field name, not a claim that every returned token is semantically a correction.

## Reused Llama.cpp APIs

The helper currently reuses these upstream APIs directly:

- model / context
  - `llama_model_load_from_file`
  - `llama_init_from_model`
  - `llama_decode`
  - `llama_batch_init`
- tokenization
  - `llama_tokenize`
  - `llama_detokenize`
  - `llama_token_to_piece`
- logits / sampling
  - `llama_get_logits_ith`
  - `llama_sampler_apply`
  - `llama_sampler_sample`
  - `llama_get_sampled_probs_ith`
  - `llama_get_sampled_candidates_ith`

It also directly reuses the upstream control-flow semantics from:

- `common_sampler_sample_and_accept_n(...)`

The current helper keeps persistent session ownership, accepted-token state, and native sampler state, but it restores the target anchor by replaying the prefix tokens instead of snapshotting sequence state. That means the following llama.cpp APIs remain relevant for future optimization work, but are not part of the current landed implementation:

- `llama_memory_seq_rm`
- `llama_memory_seq_cp`
- `llama_memory_seq_keep`
- `llama_state_seq_get_data`
- `llama_state_seq_set_data`

## Key Difference Versus The Older Project Lanes

This lane intentionally does **not** use:

- tree scoring
- piece-prefix acceptance
- observed top-k residual correction
- `token_pq`
- `draftPathSteps`

Those behaviors remain in the older experimental lanes.

`llama_cpp_spec_native` is the project's llama.cpp-style native verifier lane, not the future exact EAGLE lane.

## Build / Runtime Notes

- The helper source is `tools/desktop_target_runtime.cpp`.
- The WSL build script is `tools/build_desktop_target_runtime.sh`.
- The Windows launcher shim is `tools/desktop_target_runtime.cmd`.
- The desktop Python service now prefers the `.cmd` helper path when present.

## Validation Record

The lane has now been validated end to end on device with:

- Android local real-token draft session enabled
- desktop helper-backed target verification enabled
- multi-step speculative loop completing without falling back to legacy piece-prefix logic

Representative observed behavior from the validated run:

- verifier mode: `llama_cpp_spec_native`
- token mode: `real_token`
- acceptance mode: `llama_cpp_accept_n`
- runtime backend: `desktop_target_runtime_llama_cpp_spec_native`
- three consecutive speculative steps accepted the drafted four-token slice and appended one target follow-up token
- accumulated accepted text:
  - `I'm just a computer`
  - `I'm just a computer program, so I don`
  - `I'm just a computer program, so I don't have feelings or emotions`

This validation confirms that the lane now behaves like llama.cpp's current speculative control flow at the session level:

- draft a linear real-token slice
- verify it in one target batch
- accept the longest matching prefix
- append one target token
- continue from the updated accepted prefix

## Acceptance Criteria

The lane is considered present when all of these are true:

1. desktop can start a helper-backed target session on `llama_cpp_spec_native`
2. Android sends real-token linear draft slices to that lane
3. desktop returns:
   - accepted prefix token ids
   - one target follow-up or mismatch token
4. full-accept steps report `rejectedFromIndex = -1`
5. mismatch steps report `rejectedFromIndex = acceptedDraftCount`
6. the helper, not Python tree logic, is the source of verifier truth on this lane
