# Android Draft Runtime Probe Demo

## Purpose

This document explains the standalone probe demo that tests whether the Android draft runtime can already expose the low-level information needed for a future EAGLE-style draft runtime.

This demo is intentionally separate from the main speculative interfaces.

It does not pretend that the production draft interface is complete.

Instead, it directly tests two low-level capabilities:

1. extracting the current next-step top-k distribution from the live Android draft runtime
2. saving and restoring the current draft runtime state strongly enough that the same top-k distribution can be recovered after a sample-and-restore round trip

## Files

- `lib/src/main/java/com/example/myapplication/llama/debug/DraftRuntimeProbeDemo.kt`
- `lib/src/main/cpp/ai_chat.cpp`

## What The Demo Does

The Kotlin probe class:

- gets the current `InferenceEngine`
- loads the model if needed
- opens a temporary draft session
- asks native code for:
  - a top-k distribution snapshot
  - a state round-trip probe result

The native probe functions:

- inspect `llama_get_logits(...)`
- derive top-k candidates with probabilities
- save current context state with `llama_state_get_data(...)`
- sample one token
- restore context state with `llama_state_set_data(...)`
- compare the restored top-k view against the original top-k view
- save current sequence state with `llama_state_seq_get_data(...)`
- remove and restore that sequence with `llama_memory_seq_rm(...)` and `llama_state_seq_set_data(...)`
- compare the restored top-k view against the original top-k view again at the sequence level

## Demo API

The current entry point is:

- `DraftRuntimeProbeDemo.runTopKAndStateRoundTripDemo(...)`

The app now also exposes a temporary local-only trigger:

- `Run Draft Probe Demo`

This button appears in local mode after a model has been loaded and writes the probe output into the normal app `Output` field and diagnostic log.

It returns a plain-text report that includes:

- `capture=...`
- `roundTrip=...`
- `sequenceRoundTrip=...`
- `treeNodeCount=...`
- `treeBestPathNodeIndices=...`
- `treeNodesPreview=...`

The embedded JSON contains:

- current position
- stop generation position
- top-k candidates
- probability and log-probability per candidate
- number of bytes saved/restored
- sampled token during the mutation step
- whether the restored top-k matches the pre-sample top-k
- both whole-context and sequence-level round-trip results

## Why This Matters

This demo is the first isolated proof point for the following question:

"Can the Android draft runtime really expose the low-level data we need for a branch-aware speculative draft engine?"

If the demo works, we have evidence that:

- current logits can be extracted
- top-k candidate distributions can be exported
- context state can at least be snapshotted and restored at a usable level
- sequence-level state can at least be snapshotted and restored at a usable level

That does not mean EAGLE-style branching is already implemented.

It means the first low-level capability check is no longer theoretical.

More specifically, the demo now probes both:

1. whole-context save / restore
2. sequence-level save / restore

The second one is much closer to what a future branch-aware draft runtime will actually need.

## Current Limitation

This demo still uses the current single active runtime and does not yet create multiple simultaneously alive branch runtimes.

So it proves:

- probability extraction
- basic state round-trip viability

It does not yet prove:

- multi-branch KV-copy runtime
- branch keep / prune
- full EAGLE draft-side behavior

The demo now also prints a compact local draft-tree summary so the first branch-expanded tree can be inspected without going through the desktop verifier path.
