# 2026-04-01 Real-Token Draft API Skeleton

## What Changed

- The Android `:lib` runtime now exposes parallel experimental APIs for real-token draft work:
  - real-token draft token generation
  - real-token draft tree generation
  - token-id detokenize/render
  - real-token apply-verified helper
- The existing legacy draft APIs were kept in place so the current speculative regression path does not lose its codepoint-compatible baseline.
- `DraftTreeProposal` now also carries a `tokenMode` field, and the desktop parser records that mode in draft-tree diagnostics.

## Why This Matters

- The project can now start moving Android draft truth toward real `llama_token` ids without immediately breaking the current `llama_true_tree` regression path.
- This is the first concrete code node that separates:
  - legacy wire-compatible draft behavior
  - experimental real-token draft behavior

## Current Limitation

- The new real-token draft APIs are not yet the app's default speculative path.
- The speculative payload and desktop verifier still need to adopt the new real-token route before standard token-space `p/q` work can be resumed safely.
