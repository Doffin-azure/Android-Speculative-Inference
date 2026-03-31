# Project Progress Summary

## Purpose

This document is the compact milestone summary for the work completed so far.

Use it when you want one place that answers:

- what has already been proven
- what code paths now exist
- what speculative milestones are complete
- what is still not real yet
- what the next implementation layer should be

For the live execution order, still use `docs/project/current-status.md` first.

## High-Level Project State

The project has already moved past the original uncertainty about whether Android can load and run a real GGUF model.

At this point, the project has three established layers:

1. Android local baseline
2. ordinary Android-to-desktop remote baseline
3. first speculative protocol and debug baseline

The remaining unfinished work is no longer baseline bring-up.

The remaining unfinished work is replacing stub speculative verification and stub draft-token production with real token-level implementations.

## Milestone 1: Android Local Baseline

Already complete:

- real `llama.cpp` Android native integration works
- the tested GGUF file loads successfully on device
- a minimal real prompt generation run succeeded on Android
- the Android local baseline has been re-confirmed with a repeat checklist

Important result:

- the earlier Android failure was caused by backend-loading configuration, not by a broken model artifact

Key references:

- `docs/project/android-local-baseline-checklist.md`
- `docs/project/current-status.md`

## Milestone 2: Desktop Runtime Baseline

Already complete:

- desktop GGUF inspection works
- desktop `llama-cli` was built successfully in WSL
- desktop `llama-cli` can load the target GGUF and generate text

This established the computer-side runtime as a trusted comparison baseline.

Key references:

- `docs/environment/desktop-gguf-runtime-supplement.md`
- `tools/gguf_check.py`

## Milestone 3: Desktop HTTP Inference Service

Already complete:

- a minimal Python desktop service exists at `tools/desktop_inference_service.py`
- the service exposes:
  - `GET /health`
  - `GET /probe`
  - `POST /v1/generate`
  - `POST /v1/speculative/start`
  - `POST /v1/speculative/propose`
  - `POST /v1/speculative/fallback`
  - `POST /v1/speculative/close`
- the service logs requests to `logs/desktop-inference-service.log`
- ordinary remote generation through the desktop service has already succeeded

Key references:

- `docs/project/desktop-inference-service-runbook.md`
- `tools/desktop_inference_service.py`

## Milestone 4: Android Ordinary Remote Path

Already complete:

- the Android app contains a remote inference client
- the app can probe desktop connectivity without involving generation
- the app can call ordinary `POST /v1/generate`
- Android-to-desktop ordinary remote inference has already completed a successful LAN validation

Important result:

- local networking, desktop binding, and the basic phone-to-computer request path have all been proven

Key references:

- `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `app/src/main/java/com/example/myapplication/ui/MainScreen.kt`

## Milestone 5: Speculative Protocol Baseline

Already complete:

- the first speculative protocol draft exists
- the first Chinese implementation guide exists
- the project has a documented `start / propose / fallback / close` message set
- the project has explicit accepted-prefix, correction-token, and fallback rules

Key references:

- `docs/project/speculative-decoding-protocol-draft.md`
- `docs/project/speculative-decoding-implementation-guide-zh.md`

## Milestone 6: Desktop Speculative Session Lifecycle

Already complete:

- desktop speculative sessions can be created
- draft proposals can be sent and logged
- sessions can be closed cleanly
- ordinary remote fallback remains available

This first established the protocol lifecycle before true verification existed.

## Milestone 7: Desktop Verify-Semantics Stub

Already complete:

- the desktop `propose` path no longer blindly accepts every proposal
- it now returns:
  - `acceptedCount`
  - `rejectedFromIndex`
  - `correctionTokenIds`
- mismatch counts and accepted-token counts are tracked in session state

Current reality:

- this is still not real target-model token verification
- it is a deterministic prompt-derived verifier stub

Why it matters:

- accepted-prefix and correction-token protocol semantics are now real enough to debug end to end

## Milestone 8: Android Speculative Debug Path

Already complete:

- the app contains a `SPECULATIVE` mode
- the app can start a speculative session
- the app can send a one-step speculative proposal
- the app can close the session
- the app shows speculative summaries and diagnostics
- the app has a force-mismatch debug path

Important verified result:

- both the happy path and the correction path have already been exercised from the device UI

That means the phone side already proves:

- accepted-prefix display
- rejected-index display
- correction-token display
- mismatch regression testing from the UI

## Milestone 9: Verifier Mode Boundary

Already complete:

- the desktop service now exposes explicit speculative verifier modes
- currently supported modes are:
  - `prompt_stub`
  - `llama_preview`
- Android now surfaces the active verifier mode in probe results, session summaries, and dedicated UI state

Why it matters:

- the project now has a cleaner boundary between:
  - the current regression harness
  - the future llama-backed verifier

## Milestone 10: Llama Preview Bridge

Already complete:

- when the desktop service runs in `llama_preview`, session start prepares a llama-backed preview string
- Android already displays that preview text
- a real device validation already confirmed that the app can see:
  - `Speculative verifier mode: llama_preview`
  - a non-empty `Target preview text`

Current limitation:

- `llama_preview` currently improves visibility only
- the active `propose` verification path still does not use real target-model next-token verification

## What Is Proven Right Now

These statements should now be treated as established:

- Android local real-model runtime is proven
- desktop local real-model runtime is proven
- ordinary Android-to-desktop remote generation is proven
- speculative session lifecycle is proven
- speculative accepted-prefix and correction-token semantics are proven through stubs
- Android can deliberately trigger and display correction behavior
- verifier mode and llama-backed preview visibility are proven

## What Is Still Stubbed

These parts are still not the final implementation:

- Android draft tokens are still placeholder prompt-derived token ids
- desktop speculative verification is still not based on target-model token-by-token verification
- `llama_preview` provides preview text, not full target token verification
- speculative sessions are still debug-first, not performance-first

## Current Main Technical Gap

The main missing layer is now very specific:

- replace deterministic prompt-derived desktop verification with real target-model token verification

After that, the next missing layer will be:

- replace Android placeholder draft tokens with real local-model draft tokens

That ordering is still the lowest-risk path.

## Recommended Next Implementation Order

1. keep the current Android speculative debug harness as the regression path
2. upgrade desktop `llama_preview` from preview-only visibility to verification input
3. replace desktop stub verification with real target-model token verification
4. only then move down into `:lib` to expose real local draft tokens on Android
5. keep ordinary remote fallback active throughout

## Useful File Map

Core desktop path:

- `tools/desktop_inference_service.py`
- `docs/project/desktop-inference-service-runbook.md`

Core Android path:

- `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `app/src/main/java/com/example/myapplication/ui/MainScreen.kt`

Protocol and planning:

- `docs/project/current-status.md`
- `docs/project/speculative-decoding-protocol-draft.md`
- `docs/project/speculative-decoding-implementation-guide-zh.md`

## Resume Rule

If work resumes later, use this sequence:

1. read `docs/project/current-status.md`
2. read this file for the milestone summary
3. read `docs/project/desktop-inference-service-runbook.md` if desktop service behavior is involved
4. continue from the desktop-side real verifier replacement, not from earlier baseline bring-up
