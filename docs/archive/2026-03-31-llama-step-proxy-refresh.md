# 2026-03-31 Llama Step Proxy Refresh

## Summary

This node extends the speculative desktop verifier boundary with a new `llama_step_proxy` mode.

The service still does not perform true target-model token verification.

However, it no longer depends only on the fixed llama preview captured at session start.

## What Changed

- `tools/desktop_inference_service.py` now supports `--speculative-verifier-mode llama_step_proxy`
- `llama_step_proxy` starts from the same llama-backed preview flow as `llama_preview`
- during `propose`, the service can now refresh the preview text when the current proposal needs more target coverage than the session-start preview provides
- the accepted-prefix and correction-token semantics remain stable, and the existing Android speculative client protocol does not need to change

## Why This Matters

This is the closest current verifier harness to real target verification while keeping the protocol and Android-side debug flow unchanged.

It removes one of the major limitations of the earlier preview-text proxy:

- verification was previously limited by whatever preview length happened to be generated during `startSession`

Now the service can fetch more preview text before computing accepted/correction semantics.

## Validation

Local validation completed for this node:

- `python -m py_compile tools\desktop_inference_service.py`
- `python tools\desktop_inference_service.py --check --speculative-verifier-mode prompt_stub`
- `python tools\desktop_inference_service.py --check --speculative-verifier-mode llama_preview`
- `python tools\desktop_inference_service.py --check --speculative-verifier-mode llama_step_proxy`
- local smoke test:
  - start service in `llama_step_proxy`
  - call `GET /health`
  - call `POST /v1/speculative/start`
  - call `POST /v1/speculative/propose`
  - call `POST /v1/speculative/close`

The local smoke test confirmed:

- the health endpoint reports `llama_step_proxy`
- session start reports `verifierMode = llama_step_proxy`
- speculative propose still returns accepted/correction semantics
- the session can close cleanly afterward

## New Current Position

The speculative verifier ladder is now:

1. `prompt_stub`
2. `llama_preview`
3. `llama_step_proxy`
4. future real target-model token verification

The next technical step remains:

- replace preview-text proxy verification with real target-model token verification
