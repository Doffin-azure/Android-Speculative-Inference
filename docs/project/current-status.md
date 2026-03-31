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
- the immediate blocker is no longer "can Android load and run a real model locally"

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

## Important Files

Android runtime path:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt`
- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

Desktop GGUF validation path:

- `tools/gguf_check.py`
- `.venv-gguf/` (ignored)
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp`
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp\build-wsl-cli`

## Current Blockers

Primary blocker:

- Android local baseline is now working; the next blocker shifts to making the local baseline stable enough to support the later phone+computer architecture

Secondary blocker:

- desktop-side runtime viability is no longer a blocker; it is now a confirmed baseline for comparison

## Recommended Next Technical Step

The next step should focus on one of these:

1. record the Android local-runtime success as a completed milestone and preserve the known-good setup
2. continue validating local generation behavior with a few more prompts so the baseline is not a one-shot fluke
3. begin preparing the next stage above the local baseline instead of reopening backend-load triage

## Immediate Execution Order

Use this order unless a new runtime failure appears:

1. preserve the current Android local-runtime success as the baseline milestone
2. rerun a few small on-device prompt checks and capture diagnostics if anything regresses
3. only after the baseline still looks healthy, start the next-stage design for the computer-side normal inference service

Practical interpretation:

- do not spend the next node reopening backend-load debugging unless a fresh device run fails again
- do not spend the next node on UI polish unless it is needed to support runtime validation
- treat desktop GGUF tooling as confirmation support, not the current mainline

## Definition Of Done For The Next Node

The next node is complete when all of the following are true:

- the Android local-runtime success is explicitly recorded as a milestone in project documentation
- the known-good test setup is preserved clearly enough that the same validation can be repeated later
- at least a small set of repeat prompt checks has either succeeded again or produced captured diagnostics for the next debug pass
- the close-out includes the required git-sync explanation and markdown summary update

## After That

Once the local baseline has been re-confirmed, the next architectural step is:

1. define the computer-side normal inference service boundary
2. define the Android-to-computer normal request path
3. treat speculative decoding as a later layer on top of that ordinary remote path

## What Not To Reopen

Do not go back to:

- app scaffolding
- old app-local JNI path
- bundle workflow by Codex
- extra file-picker UX work unless a runtime issue requires it
