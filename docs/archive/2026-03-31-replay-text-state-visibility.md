# 2026-03-31 Replay Text State Visibility

## Summary

This node tightens the replay-based speculative verifier path in two ways:

1. the desktop replay verifier now prefers explicit `acceptedText` when building replay prompts
2. Android diagnostic summaries now surface that replay-session text state

## What Changed

- `tools/desktop_inference_service.py`
  - replay prompt construction now uses explicit accepted text state when available
  - replay mode still falls back to token-id debug text if explicit text is not yet available
- `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`
  - parses `acceptedText`, `lastReplayPrompt`, and `lastTargetTextDelta`
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
  - now shows replay-session text state in speculative summaries and output

## Why This Matters

Before this node, replay verification behavior already existed, but the replay prompt was still closely tied to token-id debug conversion.

That was acceptable for ASCII-oriented debugging, but it was still one step removed from the real semantic state that a future persistent verifier session will need.

Now the replay verifier uses the explicit accepted text state first, which is a cleaner bridge toward:

- stable replay prompts
- clearer debugging
- future persistent target-session verification

At the same time, Android can now surface those replay-session text fields directly, which makes verifier-state debugging less dependent on desktop-only logs.

## Validation

Local validation completed for this node:

- `python -m py_compile tools\desktop_inference_service.py`
- `python tools\desktop_inference_service.py --check --speculative-verifier-mode llama_replay_proxy`
- local smoke test confirmed that:
  - `startSession` returns replay prompt metadata
  - `proposeDraft` updates `acceptedText`
  - `closeSession` returns final `acceptedText` and `lastTargetTextDelta`

## New Current Position

The replay verifier path now has:

- replay-based continuation proxy behavior
- explicit replay-session state
- Android-visible replay-session diagnostics

The next technical step remains:

- replace replay-based proxy verification with real target-model token verification
