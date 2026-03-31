# 2026-03-31 Android First Local Draft Runtime

## What changed

- the Android local runtime now has a first real draft-session implementation instead of only an `unsupported` boundary
- `InferenceEngineImpl` now stores local draft-session metadata and rebuilds native runtime state from the current verified assistant prefix
- `ai_chat.cpp` now exposes JNI entry points for:
  - resetting draft context from `system + user + accepted assistant text`
  - sampling draft output from the real local model path
- `MainViewModel` now prefers the local draft session during speculative runs and falls back to the old stub proposal path only when the engine does not support draft sessions

## Why it matters

- this is the first node where Android speculative proposals can come from the actual on-device model runtime
- it is still not true libllama token-id drafting and it still rebuilds runtime state from verified text, but it replaces the previous UI-only stub generator with a real local-model-backed draft path

## Current limitation

- returned draft ids are still codepoint-compatible ids so that the existing desktop verifier wire format does not break
- rollback is still simulated by rebuilding native state from the current verified prefix rather than by directly rewinding libllama state
