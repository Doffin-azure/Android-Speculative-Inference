# Android Branch-Expanded Draft Tree

This node upgrades the Android local draft tree from a single best-path rollout to a shallow branch-expanded tree.

What changed:

- `ai_chat.cpp` now captures native runtime branch snapshots with `llama_state_get_data(...)`.
- The draft tree generator now restores branch snapshots, rebuilds the logits cursor with last-token replay, and explores multiple candidate children per depth.
- Best-path selection now comes from the expanded tree branches instead of blindly following the current top-1 token at every layer.
- The runtime is restored back to the root snapshot after tree generation, so probing the tree does not leave the draft session parked on the last explored branch.

What this proves:

- The Android draft runtime can now build a probability-bearing dynamic tree by revisiting multiple local branches from the same prefix.
- The earlier restore experiment was not just diagnostic; it is now part of the production draft-tree implementation.

What this still is not:

- true libllama token-id wire semantics
- KV-copy parallel branching
- full EAGLE posterior evaluation
