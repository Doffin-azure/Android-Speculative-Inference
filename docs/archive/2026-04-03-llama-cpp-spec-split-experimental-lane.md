# 2026-04-03 `llama_cpp_spec_split` Experimental Lane

## What Changed

The project now has a second native llama.cpp-style speculative verifier lane:

- `llama_cpp_spec_split`

This lane does not replace `llama_cpp_spec_native`.

It is an experimental split-contract variant that keeps:

- Android `ai_chat.cpp` as the draft-state owner
- desktop `desktop_target_runtime.cpp` as the verifier-state owner
- Python `desktop_inference_service.py` as a token-batch router only

## Code Changes

Main files:

- `tools/desktop_inference_service.py`
- `tools/desktop_target_runtime.cpp`
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

Key implementation points:

1. The desktop service now recognizes `llama_cpp_spec_split` as a real-token native verifier lane.
2. The service now routes that lane through a dedicated helper command:
   - `verify_split_draft_batch`
3. The native desktop helper now exposes a split-mode verify path that does not accept helper-side accepted-token reinjection on the hot path.
4. The Android speculative loop now treats `llama_cpp_spec_split` the same way it treats `llama_cpp_spec_native` for:
   - real-token draft requirement
   - token-only request payload
   - no `draftTree` payload on the hot path

## Why This Matters

This node is the first attempt to encode the `spec-split-draft.cpp` / `spec-split-verify.cpp` ownership model directly into the current product stack.

The main value is not transport replacement.

The main value is ownership discipline:

- draft-side continuity stays inside the Android runtime
- verifier-side continuity stays inside the desktop helper
- Python no longer pretends to be a verifier-state participant on this lane

## What It Does Not Solve Yet

- It does not remove HTTP and Python orchestration cost.
- It does not yet make Android draft continuity identical to upstream KV reuse.
- It does not yet prove a wall-clock win.

It is an experimental structural lane, not a final performance claim.
