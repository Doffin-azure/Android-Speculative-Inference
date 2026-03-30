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
- the active blocker is runtime validation on device
- the main unresolved issue is Android-side model loading/runtime behavior, not project scaffolding

## Active Technical Findings

Already resolved:

- app-local JNI path removed from active integration
- real `llama.cpp` Android native build works
- model directory selection improved
- SAF-selected models are copied into app-private storage before native loading
- native load diagnostics are more specific
- desktop GGUF inspection works
- desktop `llama-cli` has been built in WSL

Current strongest conclusion:

- the tested `Llama-3.2-1B-Instruct-Q4_K_M.gguf` file appears structurally valid on the computer
- Android-side load failure is therefore more likely to be caused by runtime compatibility or Android integration details than by an obviously corrupt model file

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

- Android app still fails to load the model at runtime even though the file itself looks valid on the computer

Secondary blocker:

- desktop-side CLI runtime has been built, but a full successful generation run with the target model has not yet been fully confirmed in the documented environment

## Recommended Next Technical Step

The next step should focus on one of these:

1. continue Android-side native load debugging with this same model
2. continue desktop-side CLI execution until a successful generation run is confirmed
3. compare Android-side behavior against desktop-side behavior using the same GGUF file

## What Not To Reopen

Do not go back to:

- app scaffolding
- old app-local JNI path
- bundle workflow by Codex
- extra file-picker UX work unless a runtime issue requires it
