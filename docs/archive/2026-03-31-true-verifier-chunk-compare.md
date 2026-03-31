# 2026-03-31 True Verifier Chunk Compare

## Summary

This node moved the first true desktop verifier beyond one-token proof behavior.

## What Changed

- the desktop true verifier now fetches a small target continuation chunk for the current accepted prefix
- one verifier call can now compare a proposal against multiple target tokens
- accepted-prefix and correction-token results can now come from one chunk fetch instead of one target call per token

## Why It Matters

This is a real step toward practical speculative verification.

The verifier is still replay-based, but it is now closer to the small-chunk behavior the final design needs.

## Validation

- `python -m py_compile tools/desktop_inference_service.py`
- local monkeypatch smoke test confirmed:
  - one target fetch
  - multiple accepted tokens
  - one correction token

## Next Step

Keep pushing the true verifier toward a stronger persistent target runtime session instead of repeated replay-based chunk fetches.
