# 2026-04-01 Llama.cpp-Style Native Speculative Validation

This note records the first successful on-device validation of the `llama_cpp_spec_native` lane.

## What Was Verified

- Android opened a local real-token draft session successfully.
- The desktop service ran in `llama_cpp_spec_native` mode.
- The desktop native helper owned verifier truth through `desktop_target_runtime_llama_cpp_spec_native`.
- The speculative loop completed multiple steps without falling back to legacy piece-prefix logic.
- Each speculative step used `acceptanceMode=llama_cpp_accept_n`.

## Representative Validated Output

Observed accepted text after the completed run:

- `I'm just a computer program, so I don't have feelings or emotions`

Representative step pattern:

1. accept a four-token draft slice
2. append one target follow-up token
3. continue from the updated accepted prefix

This matches llama.cpp's current speculative session semantics:

- linear draft proposal
- target-side batch verification
- longest accepted prefix
- one appended target token after each verified slice

## Important Naming Note

The protocol field `correctionTokenIds` is still reused on this lane for wire compatibility.

Its meaning is:

- mismatch token when `rejectedFromIndex >= 0`
- follow-up token when `rejectedFromIndex == -1`

So a fully accepted speculative step still returns one token in `correctionTokenIds`, but on this lane that token is semantically the target follow-up token.
