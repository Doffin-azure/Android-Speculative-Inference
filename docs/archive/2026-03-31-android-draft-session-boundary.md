# 2026-03-31 Android Draft Session Boundary

## Summary

This node added the first explicit draft-session interface boundary on Android and in `:lib`.

The codebase now has named lifecycle methods for future true draft work:

- `supportsDraftSession`
- `startDraftSession`
- `draftNextTokenIds`
- `applyVerifiedTokens`
- `closeDraftSession`

The implementation still intentionally reports `unsupported`.

## Why It Matters

- This fixes the code-level landing zone for true draft work.
- The next implementation node can now focus on `InferenceEngineImpl` and `ai_chat.cpp` instead of re-opening interface design.

## Core Files

- `lib/src/main/java/com/example/myapplication/llama/InferenceEngine.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlm.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt`
