# 2026-03-31 Llama Preview Verifier Proxy

## Summary

This node upgraded `llama_preview` from a visibility-only mode into an active speculative verifier proxy.

The desktop service now uses the llama-generated preview text as the current accepted-prefix and correction-token source when the verifier mode is `llama_preview`.

## What Changed

Before this node:

- `llama_preview` only prepared and exposed `targetPreviewText`
- `propose` still verified against the prompt-derived stub target

After this node:

- `startSession` still prepares `targetPreviewText`
- the session target token sequence is now derived from that preview text
- `propose` compares proposals against the preview-derived target sequence
- status values now distinguish this path:
  - `accepted_by_llama_preview`
  - `corrected_by_llama_preview`

## Why This Matters

This is the first step where speculative verification uses a signal that actually came from desktop llama generation instead of from the raw prompt text.

It is still not true target-model token verification, but it is a meaningful bridge:

- protocol shape stays stable
- Android debugging path stays usable
- the desktop verifier now depends on a llama-produced continuation signal

## What Was Verified Locally

Two local smoke checks were run in `llama_preview` mode:

1. matching preview-derived proposal
   - returned `accepted_by_llama_preview`

2. mismatching preview-derived proposal
   - returned `corrected_by_llama_preview`
   - returned `acceptedCount`, `rejectedFromIndex`, and `correctionTokenIds`

## Remaining Limitation

This is still preview-text proxy verification, not true target-model token-by-token verification.

The next major step remains:

- replace preview-text proxy verification with actual target-model token verification
