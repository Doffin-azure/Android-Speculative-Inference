# 2026-04-03 Android Native Split Draft Sync

## What Changed

The Android split draft path no longer relies mainly on Kotlin-side prefix comparison and session restart logic.

Instead, `ai_chat.cpp` now owns a native split-style synchronization step:

- `syncPersistentDraftSession(sessionId, authoritativeTokenIds, predictLength)`

## Native Control Shape

The new native path stores `prompt_prefix_tokens` inside each persistent draft session snapshot.

That lets Android build the same conceptual sequence used by the split draft reference:

- `prompt_prefix_tokens + authoritative accepted assistant tokens`

The native sync path then compares that target sequence with the current live `runtime_token_history`.

## Current Native Alignment Behavior

1. If the current live runtime already matches the authoritative sequence:
   - keep it
2. If the current live runtime only has an extra speculative tail:
   - trim the tail in place with `llama_memory_seq_rm(...)`
3. If the live runtime is missing authoritative tail tokens:
   - decode only the missing tail
4. If divergence happens inside the prefix:
   - rebuild from the full target token sequence

After alignment, the runtime:

- refreshes tail logits when needed
- rebuilds sampler history from the aligned runtime token history
- updates the persistent committed snapshot

## Why This Matters

This is the first Android-side implementation step that is directly structured around the split draft reference's control model instead of around generic snapshot restore/commit only.

It is still not identical to the standalone split draft worker, but it is now materially closer:

- authoritative token sequence drives draft alignment
- speculative tail trimming happens natively
- Kotlin no longer needs to own most of that control policy
