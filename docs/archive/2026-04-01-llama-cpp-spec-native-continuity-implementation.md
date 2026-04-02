# 2026-04-01 `llama_cpp_spec_native` Continuity Implementation

## Why This Node Exists

The previous long-prompt timing run showed that `llama_cpp_spec_native` was functionally correct but too replay-heavy:

- Android draft fetch and local apply were both expensive
- desktop verifier still rebuilt anchor state and sampler state every step
- speculative wall-clock lost badly to both local and ordinary remote generation

This node records the first direct implementation step toward upstream-style runtime continuity.

## What Changed

### Android draft runtime

The real-token draft path now has a native persistent draft-session layer:

- Kotlin `startDraftSession(...)` now opens a native committed snapshot with `startPersistentDraftSession(...)`
- real-token draft fetch restores that committed snapshot with `restorePersistentDraftSession(...)` instead of rebuilding from full assistant text
- real-token apply now commits accepted verifier tokens through `commitPersistentDraftTokens(...)`
- closing a draft session now also closes the native persistent session entry

Files:

- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

Important scope note:

- this continuity work currently targets the real-token speculative mainline
- legacy codepoint draft APIs are still kept as the regression path

### Desktop target runtime helper

The native helper now keeps a session fast path:

- the helper sampler is no longer rebuilt every verify step unless sampling config changes
- `rebuild_session_anchor(...)` is now paired with `initialize_fast_path(...)`
- normal verify steps reuse the live committed anchor and trim only the temporary tail with `llama_memory_seq_rm(...)`
- anchor rebuild remains available as a fallback path when client/session state diverges

File:

- `tools/desktop_target_runtime.cpp`

### Benchmark step economics

The benchmark path now has a minimum draft-slice guard:

- speculative benchmark runs stop when the draft slice falls below the configured minimum instead of paying a likely unprofitable short-step cost

File:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

## What This Node Does Not Claim Yet

This node does not yet claim a wall-clock win.

It only claims that the implementation has moved away from the old:

- full draft replay per real-token step
- full desktop anchor rebuild per verifier step
- helper sampler free/init per verifier step

The next required step is validation:

- rebuild the desktop helper
- rerun the long-prompt LOCAL / REMOTE / SPECULATIVE comparison
- verify that `draft fetch`, `local apply`, and `remote propose` all move in the expected direction

## Remaining Gaps

- Android legacy codepoint draft path is still replay-based
- client debug rendering still adds benchmark overhead
- the new continuity path still needs real timing confirmation on device
