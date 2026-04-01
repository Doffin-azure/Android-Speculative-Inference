# 2026-04-01 Real-Token Verifier Mode Wiring

## What Changed

- The desktop service now recognizes a new experimental verifier mode:
  - `llama_true_tree_pq_tokens`
- The Android speculative loop now checks the verifier mode returned by desktop session start.
- When the mode is `llama_true_tree_pq_tokens`, Android now switches to:
  - real-token draft token generation
  - real-token draft-tree generation
  - real-token apply-verified path
  - native token detokenize for proposal/committed text rendering

## Why This Matters

- The project now has a clean experimental lane for unified-token work.
- The current `llama_true_tree` baseline can stay stable while the new real-token path is tested in parallel.

## Current Limitation

- This wiring step does not yet mean the desktop verifier is fully token-id keyed.
- It only means the new mode boundary now exists end to end so the next node can continue replacing the remaining mixed token-space assumptions.
