# 2026-03-31 Android Speculative Verifier Visibility

## Summary

This node exposed the desktop speculative verifier mode and target preview text in the Android app.

The app now shows verifier-side session metadata returned by `startSession`, which makes it easier to confirm whether the desktop service is running in `prompt_stub` or `llama_preview`.

## What Changed

Android-side updates now surface:

- `speculativeVerifierMode` from probe responses
- `verifierMode` from speculative session start
- `targetPreviewText` from speculative session start

These values are shown in the probe summary, speculative session summary, and speculative output summary.

## Why This Matters

The project is about to experiment with a llama-backed verifier path.

Without this visibility, it would be easy to mistake one desktop verifier mode for another during phone-side testing.

This node makes the mode boundary observable from the device UI before the real target-model verifier lands.
