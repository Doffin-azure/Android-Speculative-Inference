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
- the next active stage is connecting Android to that ordinary remote service path

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

## Important Files

Android runtime path:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt`
- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

Desktop GGUF validation path:

- `tools/gguf_check.py`
- `tools/desktop_inference_service.py`
- `.venv-gguf/` (ignored)
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp`
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp\build-wsl-cli`

## Current Blockers

Primary blocker:

- the next blocker is no longer Android local correctness
- the next blocker is adding the Android-side client path for the now-proven desktop service

Secondary blocker:

- desktop-side runtime viability is no longer a blocker; it is now a confirmed baseline for comparison

## Recommended Next Technical Step

The next step should focus on one of these:

1. add the Android-side normal remote request client for `POST /v1/generate`
2. add a simple app-level distinction between local and remote inference mode
3. preserve the local path as fallback while validating the remote path

## Immediate Execution Order

Use this order unless a new runtime failure appears:

1. use `docs/project/desktop-inference-service-runbook.md` as the current desktop-service reference
2. add the smallest Android client that can call `POST /v1/generate`
3. expose a minimal local/remote mode choice in the app without replacing the local baseline
4. only after the ordinary remote path works end to end, plan speculative decoding on top of it

Practical interpretation:

- do not reopen backend-load debugging unless a fresh device run fails again
- do not jump straight into speculative decoding protocol work
- do not replace the proven local path while introducing the remote path
- use `docs/project/computer-inference-service-boundary.md` for architecture boundaries
- use `docs/project/desktop-inference-service-runbook.md` for the working desktop-service baseline

## Definition Of Done For The Next Node

The next node is complete when all of the following are true:

- Android can call the working desktop service through a normal request path
- the app can surface remote success or remote failure clearly
- the local Android baseline remains the fallback reference while the remote path is added
- the close-out includes the required git-sync explanation and markdown summary update

## After That

Once the ordinary remote boundary is defined, the next architectural step is:

1. add the Android-to-computer normal request path
2. validate the full local-network or localhost-bridge flow
3. treat speculative decoding as a later layer on top of that ordinary remote path

## What Not To Reopen

Do not go back to:

- app scaffolding
- old app-local JNI path
- bundle workflow by Codex
- extra file-picker UX work unless a runtime issue requires it
