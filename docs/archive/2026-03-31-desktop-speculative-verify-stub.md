# 2026-03-31 Desktop Speculative Verify Stub

## Summary

This node upgraded the desktop speculative `propose` endpoint from a blind lifecycle stub to a deterministic verify-style stub.

The desktop service now:

- computes an accepted prefix
- reports a rejected index
- returns correction token ids on mismatch
- updates per-session accepted-token and mismatch counters

## What Changed

The verification logic is still not backed by the desktop target model.

Instead, the current stub derives a deterministic target token sequence from the session prompt and compares the proposed token ids against that sequence.

That means the protocol now has real verify semantics even though it is still not real model verification.

## Why This Node Matters

This change is important because the speculative protocol can now exercise:

- accepted-prefix handling
- correction-token handling
- mismatch counting
- session advancement after correction

Those are the key protocol semantics the Android side will need even after the later switch to real target-model verification.

## What Was Verified Locally

Two smoke checks were run against the updated desktop service:

1. matching proposal
   - accepted all proposed tokens
   - returned `accepted_by_prompt_stub`

2. mismatching proposal
   - accepted only the matching prefix
   - returned `rejectedFromIndex`
   - returned one correction token
   - incremented mismatch count

## Remaining Limitation

The desktop service still does not verify against an actual target-model continuation.

The next major step remains:

- replace this deterministic prompt-derived verifier with true target-model token verification
