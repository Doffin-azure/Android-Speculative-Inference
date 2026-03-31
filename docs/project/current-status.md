# Current Project Status

## Project Goal

The long-term goal is a phone + computer cooperative speculative decoding system.

The staged path remains:

1. stabilize Android local runtime
2. validate real model load and minimal prompt generation on device
3. add a computer-side normal inference service
4. add a normal phone-to-computer path
5. build speculative decoding on top of that baseline

## Current Effective Stage

Current real stage:

- `llama.cpp` Android native build is already integrated and successful
- on-device local runtime validation has now succeeded for the current test model
- the Android local baseline has been re-confirmed through the repeat validation checklist
- the immediate blocker is no longer "can Android load and run a real model locally"
- the project now has a first working desktop HTTP inference service skeleton
- the Android app now contains a first normal remote client path and local/remote mode switch
- the project now also has a dedicated remote connectivity probe path with desktop-side request logging
- the Android-to-desktop normal remote path has now completed a successful end-to-end validation run
- the project now has a first draft of the speculative decoding protocol
- the desktop service now exposes a first speculative session lifecycle stub on top of the proven local and ordinary remote baselines
- the Android app codebase now contains a first speculative mode wired to that desktop lifecycle stub
- the desktop `propose` path now computes accepted prefixes and correction tokens through a deterministic prompt-derived verify stub
- the Android speculative mode now includes a force-mismatch debug path so correction-token behavior can be exercised from the device UI
- the desktop service now exposes an explicit speculative verifier mode so the current prompt-stub harness and a future llama-backed verifier can share the same protocol boundary
- the Android app now surfaces the active speculative verifier mode and target preview text returned by desktop session start
- the Android UI now also surfaces the active speculative verifier mode directly outside the session summary so verifier-mode changes are easier to spot during testing
- the next active stage is replacing that deterministic verify stub with real target-model token verification

## Active Technical Findings

Already resolved:

- app-local JNI path removed from active integration
- real `llama.cpp` Android native build works
- model directory selection improved
- SAF-selected models are copied into app-private storage before native loading
- native load diagnostics are more specific
- desktop GGUF inspection works
- desktop `llama-cli` has been built in WSL
- desktop `llama-cli` has now successfully loaded the target GGUF and generated text
- Android diagnostics can now be copied directly from the UI or pulled from a persisted app-private log file
- Android-side model-load failure has been narrowed to a backend-loading problem instead of a bad GGUF file
- Android built-in backend loading has now restored successful model loading
- Android has now completed a real minimal prompt generation with the imported GGUF model

Current strongest conclusion:

- the tested `Llama-3.2-1B-Instruct-Q4_K_M.gguf` file appears structurally valid on the computer
- the same file also runs successfully through desktop `llama.cpp`
- Android now also loads the same file successfully after switching to the built-in ggml backend path
- the earlier Android failure was specifically caused by backend-loading configuration, not by the model artifact
- the Android local baseline should now be treated as established rather than tentative
- the first desktop `POST /v1/generate` baseline is now working locally through the new service skeleton
- the codebase now has the minimum Android-side pieces needed to call that remote service
- the project now has a separate network probe path so connectivity can be tested without involving model generation
- the ordinary remote path has now also been validated from the Android device over the LAN against the desktop service
- the speculative layer now has a first explicit message-set and state-machine draft instead of only a high-level goal
- the desktop service now exposes `start / propose / fallback / close` speculative endpoints with request logging
- the current desktop speculative implementation is intentionally still a lifecycle stub and does not yet perform target-model token verification
- the Android app now has a first speculative mode, remote client calls, and diagnostic summary fields for the desktop stub session flow
- the desktop speculative `propose` step no longer accepts every proposal blindly; it now returns `acceptedCount`, `rejectedFromIndex`, and `correctionTokenIds`
- the Android app can now deliberately trigger a mismatch and surface correction-token behavior directly in the speculative debug UI
- the desktop service now reports a `speculativeVerifierMode` and can optionally prepare a llama-backed preview text while keeping the current protocol stable

## Important Files

Android runtime path:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt`
- `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`
- `app/src/main/java/com/example/myapplication/ui/MainScreen.kt`
- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

Desktop GGUF validation path:

- `tools/gguf_check.py`
- `tools/desktop_inference_service.py`
- `.venv-gguf/` (ignored)
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp`
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp\build-wsl-cli`
- `logs/desktop-inference-service.log` (local, ignored)

## Current Blockers

Primary blocker:

- the next blocker is no longer Android local correctness
- the next blocker is no longer basic phone-to-computer reachability
- the next blocker is no longer the absence of desktop speculative endpoints
- the next blocker is no longer the absence of speculative verify semantics
- the next blocker is replacing the deterministic prompt-derived verify stub with real target-model token verification

Secondary blocker:

- desktop-side runtime viability is no longer a blocker; it is now a confirmed baseline for comparison

## Recommended Next Technical Step

The next step should focus on one of these:

1. add the first speculative session endpoints to the desktop service
2. add phone-side speculative session state above the existing local and remote paths
3. keep ordinary remote fallback active while the speculative path is introduced

## Immediate Execution Order

Use this order unless a new runtime failure appears:

1. use `docs/project/desktop-inference-service-runbook.md` as the current desktop-service reference
2. use `docs/project/speculative-decoding-protocol-draft.md` as the protocol reference
3. keep the Android speculative stub path as the regression harness
4. replace deterministic prompt-derived verification with real token verification on the desktop side
5. only after the first speculative loop works, optimize chunking or transport

Practical interpretation:

- do not reopen backend-load debugging unless a fresh device run fails again
- do not jump straight into speculative decoding protocol work
- do not replace the proven local path while introducing the remote path
- use `docs/project/computer-inference-service-boundary.md` for architecture boundaries
- use `docs/project/desktop-inference-service-runbook.md` for the working desktop-service baseline
- use `docs/project/speculative-decoding-protocol-draft.md` for the first speculative message set
- remember that the Android app currently uses ordinary HTTP, so the desktop service host must be reachable from the device or emulator
- use the probe endpoint and desktop request log first when debugging "cannot connect" failures
- treat the current local and ordinary remote paths as proven baselines, not open hypotheses

## Definition Of Done For The Next Node

The next node is complete when all of the following are true:

- the desktop service exposes the first speculative session endpoints
- the phone can open and close a speculative session cleanly
- ordinary remote fallback remains available
- the local Android baseline remains the fallback reference while the remote path is added
- the close-out includes the required git-sync explanation and markdown summary update

The desktop-side portion of that node is now complete.

The phone-side wiring is now in the codebase.

The remaining completion work is Android Studio verification of that path.

## After That

Once the ordinary remote boundary is defined, the next architectural step is:

1. define the speculative draft/verify protocol
2. decide how the phone-local model and computer-hosted model exchange token work
3. preserve fallback behavior between local-only, remote-only, and future speculative modes

That protocol-definition step is now complete at the draft level.

The next implementation step is to turn it into the first real speculative session lifecycle.

## Android Studio Verification Needed By User

For the next validation node:

- confirm the app still syncs and indexes after the new speculative mode additions
- run one speculative stub request against the desktop service and capture the session summary
- run one force-mismatch speculative request and capture the correction-token summary
- keep one known-good ordinary remote run recorded as the fallback reference

## What Not To Reopen

Do not go back to:

- app scaffolding
- old app-local JNI path
- bundle workflow by Codex
- extra file-picker UX work unless a runtime issue requires it
