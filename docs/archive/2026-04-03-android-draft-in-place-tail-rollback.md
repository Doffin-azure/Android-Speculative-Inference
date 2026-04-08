# Android Draft In-Place Tail Rollback

## Purpose

This node records the first draft-side move from committed snapshot persistence toward upstream-style in-place continuity.

The project still keeps a committed snapshot per Android draft session, but it now tries to roll the live runtime back to that committed state by trimming only the speculative tail.

## Previous State

After the earlier committed-runtime reuse node:

- the project could skip restore when the live runtime already exactly matched the committed snapshot
- but once drafting advanced the runtime beyond the committed prefix, the next restore/commit path still fell back to full sequence-state restore

## Current Change

For the active persistent draft session, the Android native runtime now tries this order:

1. if the live runtime already matches the committed snapshot:
   - return immediately
2. else, if the live runtime still belongs to the same session and its token history still extends the committed prefix:
   - trim the speculative tail in place with `llama_memory_seq_rm(...)`
   - restore host-side counters and buffers
   - rebuild the logits cursor from the last committed token
3. only if that rollback path fails:
   - fall back to full sequence-state restore

## Why This Matters

This is the first Android draft continuity step that directly resembles upstream `llama.cpp`'s preferred behavior:

- keep one live draft runtime
- remove only the uncommitted speculative tail
- continue from the committed prefix

The current project still does not fully match upstream because it still keeps committed snapshots as the recovery source.

But the hot path is now closer to:

- in-place rollback first
- full restore second

instead of:

- full restore every time

## Remaining Gap

The main remaining draft-side differences versus upstream are now:

- the committed snapshot is still a first-class mechanism, not only a rare recovery path
- the Android draft runtime still does not own a fully local `accept(n_accepted)` lifecycle in the same process as verification
- the project still pays cross-device orchestration costs that upstream does not have
