# Split Parity Tracker

## Purpose

This document makes `reference/spec-split-demo-project` the fixed source-of-truth baseline for the split speculative design.

The project now treats two experiment paths as directly comparable variants of the same design:

- local reference split:
  - `reference/spec-split-demo-project`
  - native draft worker + native verify worker
  - same-machine dual-process execution
- Android + desktop split:
  - Android app draft runtime in `lib/src/main/cpp/ai_chat.cpp`
  - desktop verifier helper in `tools/desktop_target_runtime.cpp`
  - desktop orchestration in `tools/desktop_inference_service.py`
  - split across two devices

The engineering goal is not to invent a separate Android protocol.

The goal is to keep the Android + desktop path source-level aligned with the reference split design, while moving the two workers onto different devices.

## Required Comparison Rule

From this point on, every meaningful `llama_cpp_spec_split` optimization pass should compare against the reference split baseline in at least one of these dimensions:

- control flow / ownership
- request or transport boundary
- state continuity behavior
- rollback semantics
- acceptance behavior
- timing and throughput

When possible, use paired runs with:

- `reference/spec-split-demo-project/run_recorded_native_full_experiment.ps1`
- `tools/run_android_spec_split_experiment.ps1`

or the combined wrapper:

- `tools/run_split_parity_experiment.ps1`
- `tools/run_split_parity_experiment.cmd`

## Source Alignment Checklist

Reference split draft worker responsibilities:

- hold persistent draft context
- align local draft runtime to authoritative accepted tokens
- roll back speculative tail in place when possible
- generate only the next draft slice

Android draft runtime should match that shape:

- `lib/src/main/cpp/ai_chat.cpp`
- `app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt`

Reference split verify worker responsibilities:

- hold persistent verifier context
- decode `[last accepted token + drafted slice]` in one batch
- run `common_sampler_sample_and_accept_n(...)`
- append accepted prefix and one follow-up token
- roll back uncommitted verifier tail in place

Desktop verifier helper should match that shape:

- `tools/desktop_target_runtime.cpp`
- `tools/desktop_inference_service.py`

Python service responsibilities should stay thin:

- session lifecycle
- helper process control
- HTTP shaping
- experiment logging

It should not grow verifier logic that already exists in the native helper unless the helper boundary is missing data.

## Current Bottleneck Ledger

Confirmed Android-side costs:

- mobile CPU throughput is lower than desktop WSL/native baseline
- authoritative sync still pays non-trivial per-step runtime maintenance cost
- sampler history rebuild remains O(prefix) on the draft side
- tail-logit refresh is still needed on some sync paths
- JNI / app-private device environment adds extra orchestration overhead outside pure draft compute

Confirmed desktop-side costs:

- helper round-trip still adds transport overhead versus same-process reference
- Python service still adds request framing and response parsing cost
- desktop helper used to detokenize full accepted text every round; this is now removed from the hot path

Confirmed system-level gap versus local reference:

- cross-device split adds ADB/device orchestration, phone thermal limits, and network/HTTP boundaries that do not exist in the local dual-process reference run

## Latest Five-Cycle Result

Latest completed optimization loop on `2026-04-08` ran five consecutive Android split experiments after the first stable paired parity baseline.

Strongest findings:

- the most effective immediate improvement was reducing draft slice size:
  - fixed `16 -> 8` cut total run time from about `12.1s` to `4.6s` on the tested prompt
  - accepted/proposed improved from `5.20%` to `10.96%`
- the best overall result came from a conservative adaptive policy:
  - `initialDraftTokens=4`
  - `draftMaxTokens=6`
  - `adaptiveDraftMinTokens=1`
  - zero-accept steps halve the next proposal size
  - growth happens only after repeated positive accept steps
- that conservative policy produced:
  - run `2026-04-08T12-00-26+08-00`
  - `committedTokens=64`
  - `totalProposedTokens=58`
  - accepted/proposed `= 34.48%`
  - `overallTokensPerSecond=8.925`

The important interpretation is narrower than "Android is now solved":

- the phone path improved most by limiting wasted speculation
- once the draft/target distributions diverge later in the answer, Android still collapses toward very small proposals
- that means the dominant remaining issue is draft/target alignment quality after the early easy prefix, not just raw phone-side decode speed

## Android Local Baseline

The project now also keeps a second Android-side comparison lane:

- Android local single-device baseline
  - same phone
  - same 1B draft model
  - same prompt
  - same `64` token budget
  - no remote verifier
- Android + desktop split lane
  - same Android draft model and prompt
  - remote 3B verifier on desktop

This baseline is recorded through:

- `tools/run_android_local_experiment.ps1`
- `tools/compare_android_local_vs_split.ps1`

Latest same-condition comparison on `2026-04-08` showed:

- Android local draft-loop throughput: `17.665 tok/s`
- Android split draft-side throughput: `20.619 tok/s`
- Android split end-to-end throughput: `8.925 tok/s`
- Android split remote-propose share: `59.07%`

That changes the bottleneck reading in an important way:

- the phone-local draft runtime is not currently the primary limiter
- the primary limiter is the cooperative split boundary after the phone has already drafted:
  - remote verify latency
  - too many correction-driven short rounds
  - late-stage draft/target divergence that collapses the system toward 1-token proposals

## Latest Interface Alignment

The split lane has now been tightened one step closer to the local reference `model-native-full` contract:

- desktop verify session rebuild is now token-native
  - it rebuilds from prompt-prefix token ids plus accepted verifier token ids
  - it no longer depends on `acceptedText` detokenize/re-tokenize for anchor-state reconstruction
- desktop verify sampler history is now rebuilt from the full known sequence, not only accepted generated tokens
- helper sampling config for `llama_cpp_spec_split` is now aligned to the Android greedy draft defaults
- Android draft session start now captures prompt-prefix tokens through an explicit helper

This matters because it removes one interface-level mismatch before further performance tuning:

- remaining slowdowns after this point are more credibly attributable to the split boundary and proposal economics
- they are less likely to be artifacts from verifier-side text replay drift or sampler-history mismatch

## Latest Incremental-Commit Alignment

The next source-level parity step landed on `2026-04-08`:

- reference-style split drafting on Android no longer uses full authoritative `syncAndDraft` on every round
- instead, the draft runtime now follows the same higher-level loop as the local reference split worker:
  - generate draft slice from the live draft runtime
  - receive verifier accepted prefix plus one follow-up token
  - roll back speculative tail to the committed snapshot
  - append the newly verified tokens
  - continue drafting from that updated runtime
- this change was wired in both:
  - `app/src/main/java/com/example/myapplication/SpeculativeExperimentRunner.kt`
  - `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`

Latest measured result from that change:

- run: `2026-04-08T13-34-05+08-00`
- `committedTokens=64`
- `totalProposedTokens=67`
- accepted/proposed `= 40 / 67 = 59.70%`
- `totalMs=6653`
- `totalRemoteProposeMs=2759`
- `overallTokensPerSecond=9.620`

Refreshed Android local comparison:

- local run: `2026-04-08T13-37-34+08-00`
- comparison: `2026-04-08T13-38-40+08-00`
- Android local draft-loop throughput: `17.279 tok/s`
- Android split draft-side throughput: `41.409 tok/s`
- Android split overall throughput: `9.620 tok/s`
- Android split remote-propose share: `41.47%`

Interpretation:

- this pass materially improved parity with the reference split ownership model
- it also improved performance without reducing phone-local model speed
- the remaining main bottleneck is still the remote verifier boundary, but proposal economics are much better than the earlier micro-round dominated runs
- a follow-up experiment that raised only the experimental runner's `draftMaxTokens` from `6` to `8` did not improve throughput and was reverted

## Latest Verifier-Thread Compression

The next successful optimization on `2026-04-08` did not change speculative semantics.

It fixed an execution-configuration mismatch:

- the desktop service already had a `threads` setting
- but the exact desktop verifier helper was not consuming that thread budget
- helper-side speculative verify sessions therefore ran with the helper's default context thread count instead of the configured service thread count

The fix now:

- forwards `threadCount` from `tools/desktop_inference_service.py` into the native helper load request
- stores that thread budget in `tools/desktop_target_runtime.cpp`
- applies it to each verifier session context through `ctx_params.n_threads` and `ctx_params.n_threads_batch`
- raises the desktop service default from a fixed `2` threads to `max(4, cpu_count / 2)`

Latest measured result:

- run: `2026-04-08T14-27-55+08-00`
- `committedTokens=64`
- `totalProposedTokens=67`
- accepted/proposed `= 40 / 67 = 59.70%`
- `totalMs=5772`
- `totalRemoteProposeMs=1934`
- `overallTokensPerSecond=11.088`

Direct comparison against the earlier incremental-commit run `2026-04-08T13-34-05+08-00`:

- `totalRemoteProposeMs`: `2759 -> 1934`
- `overallTokensPerSecond`: `9.620 -> 11.088`
- remote verifier portion improved by about `1.43x`

Refreshed Android local comparison:

- local run: `2026-04-08T14-29-26+08-00`
- comparison: `2026-04-08T14-30-34+08-00`
- Android local draft-loop throughput: `17.616 tok/s`
- Android split draft-side throughput: `18.074 tok/s`
- Android split overall throughput: `11.088 tok/s`
- Android split remote-propose share: `33.51%`

Interpretation:

- this pass improved the verifier lane without changing draft/verify contract semantics
- Android-side draft compute still did not regress relative to the local-only baseline
- the main limiter is no longer overwhelmingly `remotePropose`; the split lane is now closer to balanced between verifier cost and draft-side runtime maintenance

## Latest Compression Follow-Up

Two more verifier-boundary compression passes were tested on `2026-04-08`:

1. split/native response thinning
2. native helper start-session sampling alignment

The important semantic point is that neither change altered the draft/verify contract:

- Android still owns the draft runtime state
- desktop still owns verifier state
- accepted prefix semantics, correction semantics, and rollback behavior are unchanged

The second change was the one that clearly mattered. By giving the helper its final sampling config during `start_session`, the split verifier no longer had to rebuild the sampler and replay the prompt again on round 1.

Latest measured result:

- run: `2026-04-08T14:56:01+08:00`
- output: [android_spec_split_app_output_2026-04-08T14-56-01+08-00.txt](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/reference/spec-split-demo-project/experiments/2026-04-08/android_spec_split_app_output_2026-04-08T14-56-01+08-00.txt)
- comparison: [android_local_vs_split_comparison_2026-04-08T14-57-30+08-00.json](/C:/Users/JXZ/AndroidStudioProjects/MyApplication2/reference/spec-split-demo-project/experiments/2026-04-08/android_local_vs_split_comparison_2026-04-08T14-57-30+08-00.json)
- `totalMs=5669`
- `totalRemoteProposeMs=1840`
- `overallTokensPerSecond=11.289`
- split remote share: `32.46%`

Direct comparison against the earlier thread-budget best run `2026-04-08T14:27:55+08:00`:

- `totalRemoteProposeMs`: `1934 -> 1840`
- `totalMs`: `5772 -> 5669`
- step 1 `prepareMs`: about `142-160 ms -> 0 ms`

Interpretation:

- parity is still preserved because only helper startup/state preparation changed
- Android draft speed remains aligned with the local baseline
- the remaining bottleneck is still not just transport; it is the persistent verifier round cost

## Recording Rule

Every new split optimization experiment must record:

- timestamped raw artifacts
- the exact script used
- whether the run is reference local, Android split, or paired
- the concrete source change being tested
- the strongest remaining bottleneck after the run

Recommended record locations:

- `reference/spec-split-demo-project/EXPERIMENT_INDEX.md`
- `reference/spec-split-demo-project/EXPERIMENT_TIMING_YYYY-MM-DD.md`
- `docs/project/current-status.md`

## Stop Condition

Keep iterating until one of these happens:

- a bottleneck is improved and re-measured
- a bottleneck is proven to be device/platform-limited for now
- a blocker cannot be resolved without changing upstream `llama.cpp` or device policy/runtime limits

At each stop point, sync git so the measurement and code state stay aligned.
