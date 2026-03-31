# 2026-03-31 Llama-Server True Verifier Bridge

## Summary

This node connected the first desktop true verifier to an optional `llama-server` backend.

The desktop service still exposes the same speculative HTTP protocol, but `llama_true_step` can now use:

- a fixed `llama-server` slot
- `cache_prompt=true`
- deterministic `/completion` calls

instead of relying only on standalone `llama-cli` replay.

## Why It Matters

- This is the first runtime step away from pure replay-only true verification.
- The desktop target session now tracks runtime backend and chunk-position state explicitly.
- The verifier path is still protocol-compatible with the current Android speculative regression client.

## Core Files

- `tools/desktop_inference_service.py`
- `docs/project/speculative-core-code-explanation.md`
- `docs/project/desktop-inference-service-runbook.md`
