# 2026-03-31 Android Speculative Multi-Step Loop

## Summary

This node upgrades the Android speculative stub client from a single `start -> propose -> close` sequence to a short multi-step loop inside the same speculative session.

The Android app still does not produce real local-model draft tokens.

However, the regression harness is now able to exercise speculative session progress over more than one draft step.

## What Changed

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt` now runs up to a short bounded sequence of speculative draft steps in one session
- the Android stub keeps track of committed token ids across steps
- the first step can still force a mismatch for correction-path testing
- later steps reuse the same session and continue from the accumulated committed token prefix
- session summaries, remote result summaries, and output text now include per-step traces

## Why This Matters

Earlier Android speculative validation proved:

- session lifecycle
- accepted-prefix display
- correction-token display

But it still stopped after a single draft step.

That meant the app could not stress the more interesting part of the desktop verifier ladder:

- session continuity
- accepted-prefix accumulation
- replay-driven continuation checks across multiple proposals

The new Android loop makes the stub harness closer to the eventual real local-draft flow, even before `:lib` exposes true draft token ids.

## Current Scope

This is still a debug-first harness:

- draft tokens are still stub tokens
- the loop is intentionally short and bounded
- the purpose is to validate protocol and session behavior, not performance

## New Current Position

The project now has:

1. desktop proxy verifier ladder through `llama_replay_proxy`
2. Android speculative client support for short multi-step session progression

The next technical step remains:

- replace replay-based proxy verification with real target-model token verification
