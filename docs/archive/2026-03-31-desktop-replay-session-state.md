# 2026-03-31 Desktop Replay Session State

## Summary

This node does not yet introduce true target-model token verification.

Instead, it strengthens the desktop speculative verifier session model by storing explicit replay-oriented state:

- `acceptedText`
- `lastReplayPrompt`
- `lastTargetTextDelta`

## What Changed

- `tools/desktop_inference_service.py` now stores replay-session text state alongside token-id state
- `startSession` returns the current `acceptedText` and exposes the initial replay prompt in debug metadata
- `proposeDraft` updates and returns:
  - `acceptedText`
  - `lastTargetTextDelta`
  - `debug.lastReplayPrompt`
- `closeSession` now also returns:
  - `acceptedText`
  - `lastTargetTextDelta`

## Why This Matters

Up to this point, the speculative desktop verifier ladder already had progressively stronger proxy behavior:

1. `prompt_stub`
2. `llama_preview`
3. `llama_step_proxy`
4. `llama_replay_proxy`

But the session state itself was still mostly token-array oriented.

This new explicit text-oriented replay state makes the future move to a persistent target verifier session easier to reason about and easier to debug.

It also gives a better bridge between:

- current replay-proxy behavior
- future real target-model verification behavior

## Validation

Local validation completed for this node:

- `python -m py_compile tools\desktop_inference_service.py`
- `python tools\desktop_inference_service.py --check --speculative-verifier-mode llama_replay_proxy`
- local smoke test:
  - start service in `llama_replay_proxy`
  - call `startSession`
  - call `proposeDraft`
  - call `closeSession`

The local smoke test confirmed:

- `startSession` returns `acceptedText = ""`
- `startSession.debug.lastReplayPrompt` is populated
- `proposeDraft` returns updated `acceptedText`
- `closeSession` returns the final `acceptedText` and `lastTargetTextDelta`

## New Current Position

The speculative desktop path now has both:

- a replay-based proxy verifier
- explicit replay-session state

The next technical step remains:

- replace replay-based proxy verification with real target-model token verification inside a persistent target session
