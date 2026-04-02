# 2026-04-01 Llama.cpp-Style Native Speculative Long-Prompt Timing

This note records a long-prompt device run on the `llama_cpp_spec_native` lane where functionality succeeded but end-to-end wall-clock latency did not improve.

## What Was Confirmed

- The Android app ran in speculative mode with `verifierMode=llama_cpp_spec_native`.
- The Android side opened a local real-token draft session successfully.
- The desktop helper remained the verifier truth through `desktop_target_runtime_llama_cpp_spec_native`.
- The speculative loop stayed on:
  - `tokenMode=real_token`
  - `acceptanceMode=llama_cpp_accept_n`
- The step trace still matched the intended llama.cpp-style semantics:
  - accept a draft prefix
  - append one target follow-up token
  - continue from the updated accepted prefix

## Representative Observed Result

Observed speculative timing for the long prompt:

- total speculative run: `44442 ms`
- speculative start session: `10182 ms`
- local draft open: `3571 ms`
- total draft fetch: `10297 ms`
- total remote propose: `9600 ms`
- total local apply: `10377 ms`
- close session: `362 ms`

Observed comparison baselines for the same prompt:

- local run: `10706 ms`
- ordinary remote run: `28602 ms`

So this run confirmed:

- the lane is functionally working
- the lane is not yet faster end to end on this workload
- the current bottleneck is implementation overhead, not verifier-mode fallback

## Step Pattern

Representative speculative trace:

1. Step 1 accepted `1` drafted token and appended `1` target follow-up token.
2. Step 2 accepted `4` drafted tokens and appended `1` target follow-up token.
3. Step 3 accepted `4` drafted tokens and appended `1` target follow-up token.

Observed committed text after the run:

- `**What is Speculative Decoding?**`
- `Speculative decoding`

This matters because the verifier was not stuck in immediate rejection. The lane was accepting useful draft work, but the fixed and per-step overhead still dominated the total run time.

## Main Interpretation

The negative result is not that `llama_cpp_spec_native` failed semantically.

The negative result is that the current implementation still pays too much for:

- target-session start
- Android draft runtime reset / fetch
- Android apply-verified replay / rebuild

Under a long prompt, those costs grew enough that speculative wall-clock time became worse than both:

- Android local generation
- ordinary remote generation

## Current Engineering Conclusion

The next optimization work should focus on runtime continuity and state reuse, not on changing the acceptance algorithm first.

The main pressure points exposed by this run are:

- Android draft session operations still appear replay-heavy
- desktop helper start cost is still high for long prompts
- each speculative step currently drafts only a short slice, so fixed per-step costs are not yet amortized well

## Why This Node Matters

This run is the first explicit timing record on the `llama_cpp_spec_native` lane showing all of these at once:

- token-native Android draft
- native helper-backed desktop verification
- successful llama.cpp-style accept-and-follow-up behavior
- negative wall-clock outcome on a realistic long prompt

That makes it a useful boundary marker:

- correctness / control-flow validation for this lane is now real
- performance work can now move to state persistence, replay elimination, and step-size economics
