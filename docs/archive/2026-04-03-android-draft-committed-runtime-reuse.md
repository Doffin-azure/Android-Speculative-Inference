# Android Draft Committed-Runtime Reuse

## Purpose

This node records a small but concrete continuity improvement on the Android real-token draft path.

The project still uses committed snapshot persistence for `llama_cpp_spec_native`, but it now avoids restoring that committed snapshot again when the same draft session is already live at the committed state.

## Previous State

Before this node:

- `startPersistentDraftSession(...)` created a committed snapshot
- `commitPersistentDraftTokens(...)` updated that committed snapshot
- but the next `restorePersistentDraftSession(...)` still reloaded sequence state even if the current native runtime already matched that same committed state

So the project was paying some restore overhead that was not semantically necessary.

## Current Change

The native Android draft runtime now tracks:

- which persistent draft session is currently active
- whether the live native runtime already matches that session's committed snapshot

The runtime is now marked as committed/aligned after:

- `startPersistentDraftSession(...)`
- `commitPersistentDraftTokens(...)`
- successful explicit restore

It is marked unaligned after:

- drafting real tokens through `generateDraftRealTokenIds(...)`

So `restorePersistentDraftSession(...)` can now short-circuit when:

- the requested session is already active
- the live runtime already matches the committed snapshot

## Why This Matters

This does not yet make Android draft continuity equivalent to upstream `llama.cpp`.

Upstream still does in-place prompt/KV reuse and tail trimming inside a persistent draft context.

But this node removes one class of redundant sequence-state round-trip in the current project and makes the committed-session fast path a little closer to a true persistent runtime.

## Remaining Gap

The main draft-side continuity gap is still:

- committed snapshot restore/commit is heavier than upstream live-context reuse
- accepted/rejected draft handling still closes the loop through cross-device orchestration rather than a same-process `accept(n_accepted)` path
