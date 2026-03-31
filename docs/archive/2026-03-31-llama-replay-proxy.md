# 2026-03-31 Llama Replay Proxy

## Summary

This node extends the speculative desktop verifier ladder with `llama_replay_proxy`.

The project still does not have true target-model token verification.

However, the verifier no longer depends only on:

- prompt-derived token ids
- a fixed llama preview captured at session start
- a preview buffer that is merely refreshed for length

It can now rebuild target continuation proxy text from the already accepted assistant prefix.

## What Changed

- `tools/desktop_inference_service.py` now supports `--speculative-verifier-mode llama_replay_proxy`
- replay mode builds a prompt that includes:
  - the original system prompt
  - the original user prompt
  - the already accepted assistant prefix
- the service then runs `llama-cli` again to obtain the next continuation proxy for verification
- `propose` can now return:
  - `accepted_by_llama_replay`
  - `corrected_by_llama_replay`
- replay-mode preview text is filtered more cleanly so banner noise and prompt echo do not dominate the returned continuation

## Why This Matters

This is the closest current verifier harness to real target continuation checking while keeping the current Android protocol unchanged.

Compared with earlier modes:

1. `prompt_stub`
   verifies against prompt-derived token ids only
2. `llama_preview`
   verifies against one llama preview captured at session start
3. `llama_step_proxy`
   can refresh that preview when more target coverage is needed
4. `llama_replay_proxy`
   regenerates target continuation from the current accepted assistant prefix

This makes the verifier depend on speculative session progress, not only on static prompt text.

## Validation

Local validation completed for this node:

- `python -m py_compile tools\desktop_inference_service.py`
- `python tools\desktop_inference_service.py --check --speculative-verifier-mode llama_replay_proxy`
- local smoke test:
  - start service in `llama_replay_proxy`
  - call `POST /v1/speculative/start`
  - use returned preview text to build a matching proposal
  - call `POST /v1/speculative/propose`
  - confirm `status = accepted_by_llama_replay`
  - call `POST /v1/speculative/close`

The local smoke test confirmed:

- replay mode starts successfully
- replay mode returns non-empty continuation preview text
- replay mode computes accepted-prefix semantics through `propose`
- the session closes cleanly afterward

## New Current Position

The speculative desktop verifier ladder is now:

1. `prompt_stub`
2. `llama_preview`
3. `llama_step_proxy`
4. `llama_replay_proxy`
5. future real target-model token verification

The next technical step remains:

- replace replay-based proxy verification with real target-model token verification inside a persistent target session
