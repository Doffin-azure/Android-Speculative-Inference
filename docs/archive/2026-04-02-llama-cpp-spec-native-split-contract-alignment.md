# `llama_cpp_spec_native` Split-Contract Alignment

## Purpose

This node records the first explicit protocol-shape alignment between the project's `llama_cpp_spec_native` lane and upstream `llama.cpp` speculative draft/verifier exchange.

The focus here is not acceptance semantics.

The focus is narrowing the hot-path contract so the draft side and verifier side exchange only the token-level information that the native verifier lane actually needs.

## Upstream Reference

Upstream `llama.cpp` speculative decoding exchanges a very small set of information between the outer loop, the draft implementation, and the verifier logic:

- current accepted target prefix tokens
- `id_last`
- drafted token ids
- accepted-draft count / accepted prefix plus one target token

Relevant source files:

- `reference/llama.cpp-upstream/examples/speculative-simple/speculative-simple.cpp`
- `reference/llama.cpp-upstream/common/speculative.cpp`
- `reference/llama.cpp-upstream/common/sampling.cpp`

## Previous Project State

Before this node, the project already skipped hot-path rendering work for `llama_cpp_spec_native`, but the protocol shell still sent:

- `proposedText`
- optional `draftTree`

even though the native helper lane only made verifier decisions from:

- `proposedTokenIds`
- target-session state on desktop

## Current Change

The `llama_cpp_spec_native` lane now narrows its draft/verifier split contract:

- Android still constructs `SpeculativeProposeRequest`
- but on this lane it now sends:
  - `sessionId`
  - `draftStep`
  - `proposedTokenIds`
  - `maxCorrectionTokens`
- it no longer sends `proposedText`
- it no longer sends `draftTree`

Desktop `propose` correspondingly:

- still parses `proposedTokenIds`
- skips `draftTree` parsing on `llama_cpp_spec_native`
- continues to call the native helper with token-only draft input

## Why This Matters

This does not yet remove the whole cross-device overhead model.

But it does remove one more mismatch between:

- the project's llama.cpp-style lane
- the older protocol/debug-oriented lanes

The current native verifier lane is now more clearly separated into:

- Android draft state owner
- desktop verifier state owner
- token-only hot-path exchange

## Remaining Gap

The project is still heavier than upstream because it still has:

- HTTP serialization
- Android/desktop split runtime ownership
- session bookkeeping and diagnostics
- native persistence costs on Android draft state

So this node should be read as:

- contract alignment
- not full runtime-cost parity
