# Android Draft EAGLE Runtime Gap

## Purpose

This document records the current assessment of whether the Android draft side can be pushed toward an EAGLE-style runtime, what capabilities are required, what capabilities already exist in the current codebase and `llama.cpp` version, and what the next capability-acquisition step should be.

It is intentionally undated so it can serve as the living reference for this topic.

## Short Answer

Yes, there is a realistic path to implement an EAGLE-inspired Android draft runtime.

The current blocker is no longer "can we access model probabilities at all".

The real blocker is that the Android draft runtime still does not manage branch state as a first-class runtime object. It can now observe top-k candidates, restore branch snapshots, and expand a shallow branch-aware tree, but it still cannot keep multiple branches alive cheaply through copy/keep/prune the way EAGLE depends on.

## What EAGLE Draft Runtime Actually Needs

To approach the draft side of EAGLE, the Android runtime needs these capabilities:

1. Persistent draft session
   The draft model state must survive across calls and remain tied to an evolving accepted prefix.

2. Next-step logits / probabilities
   The runtime must be able to inspect the model's current next-token distribution, not only sampled text output.

3. Branch snapshot / restore
   The runtime must be able to checkpoint a branch state and restore it later.

4. Branch copy / fork
   The runtime must be able to create new branches from an already computed prefix without replaying the full prompt every time.

5. Branch keep / prune
   Once verification chooses a winning branch, the runtime must be able to keep the accepted branch and discard the rest.

6. Branch-aware state progression
   Each branch must carry its own runtime position, token history, and eventually KV-backed state continuity.

Without these, the draft side can only produce a logical tree description, not a true multi-branch runtime tree.

## What We Already Have

### In Our Android Draft Runtime

The project already has:

- an explicit draft-session API boundary in `InferenceEngine`
- a first real local draft-session implementation in `InferenceEngineImpl`
- native draft runtime reset via `resetDraftContext(...)`
- sampled draft token production via `generateDraftTokenIds(...)`
- a first dynamic draft-tree proposal path via `draftTreeProposal(...)`
- top-k candidate extraction from live logits
- per-node probability and log-probability in the draft tree
- a dynamically rolled-out best path that advances with the current local runtime state
- verified whole-context and sequence-level state restore with last-token replay
- a shallow branch-expanded draft tree built from native runtime snapshot/restore

This means the draft side has already moved beyond:

- pure prompt-derived stub text
- flat token-only draft production

It can now produce:

- probability-bearing candidate nodes
- a best-path proposal conditioned on the local model runtime

### In The Current `llama.cpp` Version

The currently checked-out `llama.cpp` version already exposes the most important low-level APIs needed for the next step.

Confirmed available:

- `llama_get_logits(...)`
- `llama_get_logits_ith(...)`
- `llama_get_memory(...)`
- `llama_memory_seq_cp(...)`
- `llama_memory_seq_rm(...)`
- `llama_memory_seq_keep(...)`
- `llama_memory_seq_add(...)`
- `llama_state_get_data(...)`
- `llama_state_set_data(...)`
- `llama_state_seq_get_data(...)`
- `llama_state_seq_set_data(...)`

This means the runtime has access to:

- logits reading
- sequence-aware memory operations
- whole-context state snapshot / restore
- sequence-level state snapshot / restore

So the problem is not that the underlying runtime is missing all of the required primitives.

## What We Do Not Have Yet

The Android draft side still lacks the most important EAGLE-style runtime property:

- branch runtime state management

More concretely, the current runtime still has:

- one active `g_context`
- one active sampler chain
- one current decode path

The current draft tree therefore behaves like:

- inspect current logits
- take top-k
- roll out one best token
- inspect logits again

This is useful, but it is still only:

- single-context dynamic tree rollout

It is not yet:

- multi-branch live runtime

The current tree nodes describe candidates, but the branches are not independently alive as runtime entities.

## Why This Differs From EAGLE

EAGLE depends on more than "having a tree".

It depends on:

- direct runtime control
- branch-local KV continuity
- copying or reusing already-computed state
- selecting one branch and preserving its state cheaply

Our current Android draft runtime can observe and score candidates, but it still cannot:

- clone a branch state
- restore a branch state
- keep multiple branches alive in parallel
- prune back down to one retained branch at runtime level

That is the main structural gap.

## What We Have Successfully Acquired So Far

The first capability-acquisition step is already complete:

1. Android draft runtime can now inspect real next-step logits.
2. Android draft runtime can now derive top-k candidates.
3. Android draft runtime can now attach `probability` and `logProbability` to draft-tree nodes.
4. Android draft runtime can now produce a first dynamic tree-shaped draft proposal.
5. Android draft runtime can now restore both whole-context and sequence-level state back to the same observed top-k distribution when last-token replay is applied.
6. Android draft runtime can now expand a shallow branch-aware draft tree by revisiting multiple local branches sequentially.

This is the first real move from:

- linear draft output

to:

- probability-bearing draft-tree generation

## Next Capability To Acquire

The next capability to acquire is:

- branch copy / fork / keep / prune

That should be attempted next through:

- `llama_memory_seq_cp(...)`
- `llama_memory_seq_keep(...)`
- `llama_memory_seq_rm(...)`

because snapshot/restore is no longer hypothetical; it has already been validated and used to build the first branch-expanded tree.

## Recommended Next Implementation Direction

The next implementation node should focus on:

1. introducing native branch-state objects for the Android draft runtime
2. converting the current sequential branch-expanded tree into explicit native branch objects
3. validating that one accepted branch can be resumed while sibling branches are kept or pruned cheaply
4. only after that, attempting true multi-branch draft runtime management

This keeps the work aligned with the real missing capability instead of over-investing in higher-level tree formatting alone.

## Practical Interpretation

Current status:

- possible in principle: yes
- required runtime primitives: largely available
- already acquired: logits, top-k, probabilities, state restore, shallow branch-expanded tree
- still missing: cheap branch runtime management with copy/keep/prune semantics

So the path forward is not blocked by theory.

It is blocked by the need to turn available low-level state APIs into a real branch-aware Android draft runtime.
