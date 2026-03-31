# 2026-03-31 Desktop Speculative Verifier Mode

## Summary

This node introduced an explicit desktop-side speculative verifier mode.

The service now reports and stores a verifier mode so the project can keep the current prompt-derived regression harness while preparing for a later llama-backed verifier.

## What Changed

The desktop service now supports:

- `prompt_stub`
- `llama_preview`

`prompt_stub` remains the default and keeps the current deterministic accepted-prefix and correction-token behavior.

`llama_preview` does not yet switch the active verification semantics, but it prepares a llama-backed preview string during `startSession`.

## Why This Matters

The project previously had one speculative verifier implementation baked directly into the service.

Now the protocol boundary is cleaner:

- health and probe endpoints report the active verifier mode
- speculative sessions store that mode explicitly
- session start can surface preview information without changing the phone-side protocol

This makes it easier to evolve from the current prompt-derived stub to a future target-model verifier without rebuilding the API again.

## Current Limitation

The active `propose` logic is still prompt-derived.

So this node does not yet deliver true target-model token verification.

It mainly establishes the service-side abstraction needed for that next step.
