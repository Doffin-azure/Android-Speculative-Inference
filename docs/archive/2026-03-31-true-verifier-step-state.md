# 2026-03-31 True Verifier Step State

## Summary

This node strengthened the first true desktop verifier without changing the protocol.

## What Changed

- `llama_true_step` no longer performs an extra target-model refresh call before the verify loop
- real target-model calls now happen only inside the actual true-verifier comparison loop
- the desktop target session now records:
  - `true_verifier_call_count`
  - `last_true_expected_token_id`
  - `last_true_expected_token_text`

## Why It Matters

This makes the first true verifier:

- cheaper to run
- easier to debug
- closer to a future persistent target runtime session

without changing the HTTP lifecycle or Android regression client.

## Validation

- `python -m py_compile tools/desktop_inference_service.py`
- local monkeypatch smoke test confirmed:
  - no extra refresh-time target call in true mode
  - correct call counting
  - correct last expected token tracking

## Next Step

Continue strengthening the true verifier toward a more persistent target runtime session.
