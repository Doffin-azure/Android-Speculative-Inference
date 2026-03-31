# 2026-03-31 Desktop Target Session Boundary

## Summary

This node introduced the first explicit desktop-side target-session boundary for speculative verification work.

The service still uses proxy verifiers today, but speculative sessions and target-session state are no longer represented by only one internal object.

## What Changed

- `tools/desktop_inference_service.py` now defines a separate `TargetSessionState`
- each speculative session now receives a `targetSessionId`
- the server now keeps a dedicated `target_sessions` map
- `start / propose / close` responses now expose `targetSessionId`
- `GET /health` and `GET /probe` now expose `targetSessionCount`

## Why It Matters

This is the first code-level seam that lets the desktop verifier move from:

- `verifierStage = proxy_target`

toward:

- `verifierStage = true_target`

without first rewriting speculative-session lifecycle handling.

## Validation

- `python -m py_compile tools/desktop_inference_service.py`

## Next Step

Use the new target-session boundary as the implementation seam for the first real desktop verifier node.
