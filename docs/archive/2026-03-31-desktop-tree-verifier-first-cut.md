# 2026-03-31 Desktop Tree Verifier First Cut

## What changed

- added a new desktop verifier mode: `llama_true_tree`
- kept the existing Android speculative wire protocol unchanged
- expanded the desktop verifier internally into a shallow target-side candidate tree using `llama-server` top-k probability results
- mapped the resulting best target path back into the existing:
  - `acceptedCount`
  - `rejectedFromIndex`
  - `correctionTokenIds`
- surfaced new tree debug fields to Android:
  - `treeCandidateCount`
  - `treeBestPathTokenIds`
  - `treeBranchFactor`
  - `treeDepthEvaluated`
  - `treeDebugSummary`

## Why it matters

- this is the first verifier node that moves beyond linear chunk comparison and starts approximating the “evaluate multiple candidate continuations on the target side” shape from EAGLE-style verification
- it does that without forcing an immediate protocol change on Android

## Current limitation

- the tree is still desktop-generated, not Android-provided
- best-path scoring is still a first-cut target-side heuristic, not full posterior acceptance
- the current protocol still carries linear `proposedTokenIds`
