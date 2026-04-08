# `llama_cpp_spec_native` Helper State Ownership

## Purpose

This node records a verifier-side contract cleanup on the `llama_cpp_spec_native` lane.

The goal is to make the project's split more closely match the intended ownership model:

- Android owns draft state
- the native desktop helper owns verifier state
- the Python service remains an orchestration shell

## Previous State

Before this node, the Python service still sent `acceptedTokenIds` and `lastAcceptedTokenId` back to the helper on every `verify_draft_batch` call.

That was wider than necessary because the helper already persisted:

- committed accepted tokens
- anchor prefix tokens
- anchor last token
- fast-path verifier context

## Current Change

On the normal `llama_cpp_spec_native` hot path, the Python service now sends only:

- `sessionId`
- `draftTokenIds`
- `samplingConfig`

The helper still supports accepted-token injection as a compatibility or recovery seam, but the normal lane no longer reasserts that state on every round.

## Why This Matters

This is a small but important ownership correction:

- verifier-side committed state now stays inside the native helper
- the orchestration shell no longer redundantly mirrors it back on every step

That is closer to upstream `llama.cpp`, where speculative verification runs directly on persistent target-side state rather than receiving the full accepted prefix every round through a protocol boundary.
