# 2026-04-03 Android Split Draft Sync Interface

## What Changed

The Android local draft runtime now exposes a new split-style control interface:

- `syncRealTokenDraftSession(sessionId, authoritativeTokenIds)`

This is a new Kotlin/API boundary above the existing native `llama.cpp` draft runtime.

## Why This Node Exists

The previous Android real-token draft flow was centered on:

- restore committed state
- generate draft slice
- apply step-local verified tokens

That works, but it does not look like the control shape in the split draft reference.

The split draft reference is centered on:

- read authoritative accepted token sequence
- align local draft state to that sequence
- continue drafting from the aligned local state

This new interface is the first project-side API that encodes that control model directly.

## Current First-Pass Behavior

On the Android side:

1. If the authoritative accepted token sequence exactly matches the current local accepted token sequence:
   - no-op
2. If the authoritative sequence extends the current local accepted prefix:
   - append only the missing tail through `commitPersistentDraftTokens(...)`
3. If the authoritative sequence diverges inside the current local prefix:
   - hard realign by restarting the native draft session
   - replay the authoritative accepted token sequence through the existing native commit path

## What It Does Not Do Yet

This first pass does not yet provide full in-place LCP sync like `spec-split-draft.cpp`.

In particular:

- prefix divergence still falls back to hard realign
- the JNI/native layer still does not expose a direct `prompt_dft` object boundary

So this node should be read as:

- control interface extracted: yes
- first practical split-style synchronization path: yes
- full native draft parity with the reference split worker: not yet
