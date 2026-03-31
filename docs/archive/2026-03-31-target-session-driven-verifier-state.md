# 2026-03-31 Target Session Driven Verifier State

## Summary

This node moved the desktop verifier one step closer to true target verification.

The earlier target-session boundary is no longer only structural. The desktop verifier now refreshes and rehydrates proxy target state through `TargetSessionState` during speculative `propose`.

## What Changed

- `tools/desktop_inference_service.py` now has target-session-oriented helper functions for:
  - target preview preparation
  - target token-id resolution
  - proxy preview refresh
  - copying target-session state back into speculative-session state
- speculative `start` now seeds preview state in a form that can be shared cleanly with the target-session layer
- speculative `propose` now refreshes target proxy state through `TargetSessionState` before computing accepted and correction semantics

## Why It Matters

This means the verifier no longer depends on the speculative-session object alone as its state owner.

That is the last major refactoring step before the desktop verifier can swap its proxy engine for a true target-model verification engine.

## Validation

- `python -m py_compile tools/desktop_inference_service.py`

## Next Step

Replace the current proxy verifier logic behind the target-session layer with the first real desktop target verifier implementation.
