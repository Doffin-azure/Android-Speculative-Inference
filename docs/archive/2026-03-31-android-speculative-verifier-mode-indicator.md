# 2026-03-31 Android Speculative Verifier Mode Indicator

## Summary

This node added a dedicated speculative verifier mode indicator to the Android UI and diagnostic state.

The app already parsed verifier metadata before this node, but the mode was mainly buried inside longer summaries.

Now the current verifier mode is also exposed as its own state field so testing different desktop verifier modes is easier.

## What Changed

Android-side updates now:

- store the current speculative verifier mode as dedicated `ViewModel` state
- update that state from both probe and speculative session start
- render the mode directly near the top of the main screen
- persist that mode in the diagnostic snapshot

## Why This Matters

The project is transitioning from `prompt_stub` toward `llama_preview` and later a true target-model verifier.

Having a standalone verifier mode indicator reduces ambiguity during device-side testing and makes log screenshots easier to interpret.
