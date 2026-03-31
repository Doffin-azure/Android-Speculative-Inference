# 2026-03-31 Verifier Driver Boundary

## Summary

This node introduced an explicit verifier-driver shape inside the desktop speculative service.

The current proxy verifier behavior still exists, but it is no longer embedded as one large inline block inside `propose`.

## What Changed

- `tools/desktop_inference_service.py` now defines `VerifyComputation`
- proxy verification is now computed through dedicated helper functions
- speculative `propose` now routes verifier work through:
  - target-session refresh helpers
  - proxy verify computation
  - shared state-application helpers

## Why It Matters

This is the last major code-shape step before the first real desktop verifier can be introduced.

The next true-verifier node can replace the current proxy driver with a real target verifier engine while keeping:

- the HTTP protocol
- the Android regression client
- the speculative session lifecycle

stable.

## Validation

- `python -m py_compile tools/desktop_inference_service.py`

## Next Step

Replace the current proxy verifier computation behind the target-session driver with the first real desktop target verifier implementation.
