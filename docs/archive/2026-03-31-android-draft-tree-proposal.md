## Android Draft Tree Proposal

This node adds the first Android-side dynamic draft-tree proposal path.

What changed:

- `InferenceEngine` now exposes `supportsDraftTree()` and `draftTreeProposal(...)`.
- `InferenceEngineImpl` now calls a native `generateDraftTreeJson(...)` entrypoint and parses it into `DraftTreeProposal`.
- `ai_chat.cpp` now reads current next-step logits from `g_context`, derives top-k candidates with probabilities, and can expand a shallow branch-aware tree by saving/restoring runtime state between branch explorations.
- `MainViewModel` now prefers the local draft-tree best path when desktop verifier mode is `llama_true_tree` and the local draft tree runtime is available.

What this is:

- a first lightweight, probability-bearing draft tree
- dynamic because each level is conditioned on the locally restored branch prefix instead of a fixed prompt-only view
- still compatible with the current codepoint-based speculative wire format

What this is not yet:

- true libllama token-id wire semantics
- KV-copy branching
- full EAGLE posterior evaluation
