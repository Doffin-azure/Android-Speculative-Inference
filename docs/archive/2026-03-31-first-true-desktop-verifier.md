# 2026-03-31 First True Desktop Verifier

## Summary

This node introduced the first real desktop-side speculative verifier mode.

The new mode is:

- `llama_true_step`

It keeps the existing HTTP protocol and Android regression client, but it no longer derives verifier truth from preview text or replay proxy text.

## What Changed

- `tools/desktop_inference_service.py` now exposes `llama_true_step`
- `infer_verifier_stage()` now reports `true_target` for that mode
- speculative `propose` can now route through a true-verifier path
- the true-verifier path asks the target model for the next token on each speculative comparison step
- accepted-prefix and correction-token semantics are now computed from real target next-token work in this mode

## Validation

- `python -m py_compile tools/desktop_inference_service.py`
- `python tools/desktop_inference_service.py --check --speculative-verifier-mode llama_true_step`
- a local monkeypatch smoke test confirmed the new true-verifier path can return:
  - accepted prefix tokens
  - one correction token
  - rejected index

## Current Limitation

This is the first true verifier node, not the final one.

It still replays the prompt through `llama-cli` for each comparison step instead of holding a persistent in-memory target runtime session.

## Next Step

Strengthen `llama_true_step` toward a more persistent target runtime session while keeping the Android-side regression harness stable.
