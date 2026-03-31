# Android Local Baseline Checklist

## Purpose

This checklist is the repeatable validation path for the known-good Android local inference baseline.

Use it after the project has already achieved one successful on-device model load and generation run.

## Known-Good Baseline

Current baseline assumptions:

- Android local runtime has already loaded a real GGUF model successfully
- Android local runtime has already returned visible generated text
- the validated model is `Llama-3.2-1B-Instruct-Q4_K_M.gguf`
- the app imports the selected model into app-private storage before native loading

## Verification Boundary

These steps are performed by the user in Android Studio / on device:

- Gradle sync
- app install / run
- model picking
- on-device prompt execution
- Logcat inspection if needed

Codex support work for this node is:

- keeping this checklist current
- keeping the runtime status documentation aligned
- helping interpret diagnostics if a rerun fails

## Pre-Run Checks

Before rerunning the baseline:

1. confirm the app still opens without new IDE sync errors
2. confirm the target device is the same ABI family used by the project baseline, currently `arm64-v8a`
3. confirm the known-good GGUF file is still available for selection
4. confirm the diagnostics path shown in the app is available so failures can be copied out quickly

## On-Device Validation Pass

Run this sequence in order:

1. launch the app on device
2. pick the directory that contains the known-good `.gguf` file
3. select the known-good model if more than one candidate appears
4. press `Load Model`
5. confirm the UI reaches the equivalent of:
   - model loaded
   - no fresh error message
   - loaded model path is populated
6. run a few short prompts instead of one long prompt

Suggested prompts:

- `Hello`
- `Tell me what you are in one sentence.`
- `Count from 1 to 5.`

Expected result:

- each prompt returns visible text
- the app does not crash
- the status returns to an idle/ready state after each run

## What To Capture If Anything Fails

Capture the smallest useful bundle of evidence:

1. the exact prompt used
2. the visible UI status text
3. the visible last-error text
4. the app diagnostic snapshot path and contents when available
5. the first relevant Logcat lines for tags such as `ai-chat`, `InferenceEngineImpl`, `llama`, or `ggml`

## Pass Criteria

Treat the baseline as re-confirmed when all of the following are true:

- model load succeeds again
- at least a few short prompts generate visible output
- no new runtime blocker appears in diagnostics
- the result can be summarized as a stable repeat of the earlier Android local milestone rather than a one-off success

## If The Rerun Fails

Use this decision rule:

- if model load fails, inspect file import, native load diagnostics, and backend initialization first
- if generation fails after load succeeds, inspect prompt processing and token generation flow next
- do not reopen old preparation or architecture work until the fresh failure is understood

## After A Successful Rerun

Once this checklist passes again:

1. update `docs/project/current-status.md` if the confidence level changes
2. record a short node summary in the archive/checkpoint docs
3. move on to defining the computer-side normal inference service boundary
