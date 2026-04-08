# Collaboration Acceleration History

This document records every material optimization attempt made so far for the Android `<->` desktop speculative split lane, with emphasis on reducing middle-coordination overhead (`remotePropose` share / cooperative verifier cost).

## Current Best Result

- best split run: `2026-04-08T14:56:01+08:00`
- output: [android_spec_split_app_output_2026-04-08T14-56-01+08-00.txt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/reference/spec-split-demo-project/experiments/2026-04-08/android_spec_split_app_output_2026-04-08T14-56-01+08-00.txt)
- paired comparison: [android_local_vs_split_comparison_2026-04-08T14-57-30+08-00.json](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/reference/spec-split-demo-project/experiments/2026-04-08/android_local_vs_split_comparison_2026-04-08T14-57-30+08-00.json)
- `totalMs=5669`
- `totalRemoteProposeMs=1840`
- `overallTokensPerSecond=11.289`
- `splitRemoteShare=32.46%`
- `splitDraftTpsVsLocalDraftLoopTpsRatio=1.0304`

Interpretation:

- Android draft-side compute is now slightly faster than the refreshed phone-local baseline under the same prompt and model family.
- The main remaining gap is not raw transport alone; it is still the verifier-side cooperative round cost.
- The `<10%` target for middle-coordination loss is not yet reached.

## Kept Improvements

### 1. Persistent Android draft runtime with incremental verified-token commit

- status: kept
- main files:
  - [SpeculativeExperimentRunner.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/app/src/main/java/com/example/myapplication/SpeculativeExperimentRunner.kt)
  - [MainViewModel.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt)
  - [InferenceEngineImpl.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt)
  - [ai_chat.cpp](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/lib/src/main/cpp/ai_chat.cpp)
- change:
  - stopped doing authoritative full sync on every Android split round
  - switched to reference-style behavior: commit verified real tokens into the live draft runtime, then continue drafting from that state
- reason:
  - source-level alignment with the reference split contract
  - removes repeated draft-side replay/rebuild work
- measured effect:
  - `2026-04-08T13:34:05+08:00`
  - `totalRemoteProposeMs=2759`
  - `overallTokensPerSecond=9.620`
  - much better than the earlier micro-round dominated path and preserved acceptance ratio at `40 / 67`

### 2. Fused JNI hot path: commit verified tokens and immediately generate next draft

- status: kept
- main files:
  - [InferenceEngine.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/lib/src/main/java/com/example/myapplication/llama/InferenceEngine.kt)
  - [InferenceEngineImpl.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt)
  - [LocalLlm.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/app/src/main/java/com/example/myapplication/inference/LocalLlm.kt)
  - [LocalLlmImpl.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt)
  - [ai_chat.cpp](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/lib/src/main/cpp/ai_chat.cpp)
- change:
  - added `commitAndGenerateDraftRealTokenIds(...)`
  - folded `apply verified draft result` and `draft next batch` into one native transition
- reason:
  - reduces JNI/session bookkeeping overhead on the Android hot path
- effect:
  - part of the successful incremental-commit improvement set
  - also removed the need for measurable `localApplyMs` in the split experiment traces

### 3. Remove O(prefix) text rebuild from split hot path

- status: kept
- main files:
  - [desktop_target_runtime.cpp](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/desktop_target_runtime.cpp)
  - [desktop_inference_service.py](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/desktop_inference_service.py)
- change:
  - avoided repeated full accepted-text rebuild where the service can safely append step deltas instead
- reason:
  - removes avoidable prefix-length growth from the per-round verifier path
- effect:
  - reduces Python/helper work and makes later verifier optimizations easier to expose in timings

### 4. Desktop verifier thread-budget propagation

- status: kept
- main files:
  - [desktop_inference_service.py](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/desktop_inference_service.py)
  - [desktop_target_runtime.cpp](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/desktop_target_runtime.cpp)
  - [run_android_spec_split_experiment.ps1](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/run_android_spec_split_experiment.ps1)
- change:
  - forwarded desktop service `threadCount` into the native verifier helper
  - applied it to both `ctx_params.n_threads` and `ctx_params.n_threads_batch`
  - raised service default from fixed `2` to `max(4, cpu_count / 2)`
- reason:
  - the helper had been running with an accidental low thread budget
- measured effect:
  - `2026-04-08T14:27:55+08:00`
  - `totalRemoteProposeMs: 2759 -> 1934`
  - `overallTokensPerSecond: 9.620 -> 11.088`
  - verifier portion improved by about `1.43x`

### 5. Start helper sessions with the final split sampling config

- status: kept
- main files:
  - [desktop_inference_service.py](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/desktop_inference_service.py)
- change:
  - `start_session` for `llama_cpp_spec_native` / `llama_cpp_spec_split` now receives the same `samplingConfig` later used by `verify_draft_batch`
- reason:
  - avoids first-round `sampler rebuild + full restore` inside the helper
- measured effect:
  - `2026-04-08T14:56:01+08:00`
  - step 1 `prepareMs` dropped from roughly `142-160 ms` to `0 ms`
  - best run so far: `totalMs=5669`, `totalRemoteProposeMs=1840`, `overallTokensPerSecond=11.289`

### 6. Leaner split/native verifier response payload

- status: kept
- main files:
  - [desktop_inference_service.py](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/desktop_inference_service.py)
- change:
  - for `llama_cpp_spec_native` / `llama_cpp_spec_split`, removed per-step large warning text and trimmed debug payload to timing/runtime essentials
  - no semantic change to acceptance/correction logic
- reason:
  - reduces Python JSON assembly and Android JSON parsing overhead on every round
- measured effect:
  - isolated gain was within noise on `2026-04-08T14:54:12+08:00`
  - retained because it is a safe response-thinning step and it composes with the sampler-start alignment change above

### 7. Experiment thread sweep control

- status: kept
- main files:
  - [run_android_spec_split_experiment.ps1](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/tools/run_android_spec_split_experiment.ps1)
- change:
  - added `-Threads` parameter to sweep helper thread counts without editing source
- reason:
  - keeps verifier-thread experiments reproducible
- effect:
  - enabled quick validation that some thread counts help while severe oversubscription hurts badly

## Reverted Or Rejected Experiments

### 1. Android deterministic forcing (`temp=0`, `top_k=1`)

- status: reverted
- run: `2026-04-08T10:26:16+08:00`
- result:
  - `committedTokens=20`
  - `totalMs=41024`
  - `totalDraftFetchMs=37150`
  - `overallTokensPerSecond=0.488`
- conclusion:
  - under the current lane, deterministic forcing on Android draft was strongly harmful

### 2. Experimental runner `draftMaxTokens=8`

- status: reverted
- run: `2026-04-08T13:36:02+08:00`
- result:
  - no meaningful gain over the incremental-commit baseline
- conclusion:
  - the win came from runtime/state alignment, not a larger proposal cap

### 3. `DEFAULT_SPECULATIVE_DRAFT_P_MIN = 0.0`

- status: reverted
- run: `2026-04-08T14:47:29+08:00`
- result:
  - `totalMs=5854`
  - `totalRemoteProposeMs=2043`
  - worse than the earlier best thread-budget run
- conclusion:
  - forcing full-length greedy drafting did not help this Android split lane

### 4. HTTP keep-alive probe

- status: not kept
- runs:
  - `2026-04-08T14:27:55+08:00` baseline reference
  - `2026-04-08T14:45:13+08:00` keep-alive retest
- result:
  - `totalRemoteProposeMs` stayed effectively unchanged (`1934 ms` vs about `1997 ms`)
- conclusion:
  - raw TCP connection policy was not the dominant bottleneck here
  - the real remaining loss is cooperative verifier work, not simple socket setup alone

### 5. Oversubscribed helper threads (`-Threads 20`)

- status: rejected
- run: `2026-04-08T14:43:17+08:00`
- result:
  - `totalMs=22862`
  - `totalRemoteProposeMs=18838`
  - verifier decode exploded into roughly `700-1100 ms` per round
- conclusion:
  - oversubscription is catastrophic for this helper/model/device combination

## Reference-Boundary Deviations

These items are important because they either already crossed the reference split logic boundary, or they are still present as experiment-shell behavior that is not fully source-aligned with the reference worker contract.

### 1. Adaptive `draftMaxTokens` in the Android experiment runner

- status: active in the experiment harness
- main file:
  - [SpeculativeExperimentRunner.kt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/app/src/main/java/com/example/myapplication/SpeculativeExperimentRunner.kt)
- why it deviates:
  - the current Android harness dynamically halves or increases `currentDraftMaxTokens` based on recent accept history
  - the reference draft worker is closer to a stable `n_max` proposal contract
- scope:
  - this does not change the core verifier acceptance semantics
  - but it does change proposal policy, so it should be treated as an experiment-shell deviation rather than reference-equal core logic
- rollback method:
  - force `requestedDraftMaxTokens` to a fixed value on every round
  - remove `consecutiveZeroAcceptSteps` / `consecutivePositiveAcceptSteps` driven resizing
  - record the rollback with:
    - timestamp
    - reverted file path
    - exact constants before and after
    - one fresh Android split run proving the fixed-`n_max` path still works

### 2. Android deterministic forcing (`temp=0`, `top_k=1`)

- status: already reverted
- why it deviated:
  - it altered the Android draft sampler policy rather than only reducing execution overhead
- rollback method used:
  - restore prior sampler configuration in the Android draft path
  - rerun the same prompt/model experiment
  - record both the bad run and the reversion run in the timing log

### 3. `DEFAULT_SPECULATIVE_DRAFT_P_MIN = 0.0`

- status: already reverted
- why it deviated:
  - it pushed the Android draft side toward a different proposal truncation policy than the prior aligned setup
- rollback method used:
  - restore [ai_chat.cpp](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/lib/src/main/cpp/ai_chat.cpp) `DEFAULT_SPECULATIVE_DRAFT_P_MIN` from `0.0f` back to `0.90f`
  - rerun the Android split experiment and compare against the last known-good aligned run

## Rollback Recording Rule

Whenever a change is judged to violate the reference split logic, record the rollback the same way every time:

1. identify the exact semantic deviation
2. name the affected file and symbol or code block
3. restore the previous aligned value or control flow
4. run one timestamped Android split verification experiment after the rollback
5. log:
   - the violating run timestamp
   - the rollback timestamp
   - the restored setting
   - whether output semantics and performance returned to the prior range
6. if committed, record the reverting commit id alongside the experimental commit id

## What The Data Says Now

- Android draft compute is no longer the primary problem.
- Measured transport-only residue is already small in most rounds.
- The remaining middle-collaboration loss is mainly:
  - verifier-side decode cost per round
  - too many cooperative rounds for the amount of target text committed
  - first-class split-session orchestration overhead that still sits above raw local-only drafting

## Next Compression Directions

- reduce verifier rounds without regressing acceptance ratio
- shrink helper decode cost further without changing output semantics
- keep Android draft throughput at or above local baseline while reducing verifier share
- only count the `<10%` target as complete when `remotePropose` share, not just pure transport share, falls below `10%`
