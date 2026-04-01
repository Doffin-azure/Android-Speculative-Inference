# Documentation Library

This directory is the curated documentation library for the project.

Its purpose is to keep high-signal operational knowledge in one place instead of scattering it across root-level notes and chat history.

## Recommended Read Order

1. `project/current-status.md`
2. `environment/desktop-gguf-runtime-supplement.md`
3. `workflow/collaboration-rules.md`
4. `archive/root-document-map.md`

## What Lives Here

- `environment/`
  Desktop and runtime environment notes, including the computer-side GGUF inspection and `llama.cpp` CLI setup.
- `project/`
  Current project state, active blockers, and the next technical steps.
- `workflow/`
  Collaboration rules and repository workflow expectations.
- `archive/`
  Explanations of how the older root-level documents should be interpreted.

## Relationship To Root-Level Documents

The root-level markdown files are still retained:

- `ANDROID_APP_CHECKPOINT.md`
- `LLAMA_CPP_INTEGRATION_PLAN.md`
- `MIDTERM_REPORT.md`

They are not deleted by this documentation library.

Instead:

- the root files remain as historical or formal records
- this `docs/` tree becomes the easier operational reference set

## Current Most Useful Documents

- `project/current-status.md`
  Use this first when resuming technical work and deciding what to do next.
- `project/project-progress-summary.md`
  Use this when you want a single milestone summary of everything that has already been completed so far.
- `project/android-local-baseline-checklist.md`
  Use this when rerunning the proven Android local model-load and generation baseline on device.
- `project/computer-inference-service-boundary.md`
  Use this when starting the next stage above the local baseline: the ordinary computer-side inference service.
- `project/desktop-inference-service-runbook.md`
  Use this when starting and sanity-checking the first desktop HTTP inference service.
- `project/speculative-decoding-protocol-draft.md`
  Use this when starting the first phone-draft / computer-verify protocol design.
- `project/speculative-decoding-implementation-guide-zh.md`
  Use this when you want the Chinese implementation guide for phone-side draft and computer-side verification.
- `project/speculative-core-code-explanation.md`
  Use this when you want the current speculative implementation's core code snippets together with short explanations.
- `project/project-core-code-history.md`
  Use this when you want the git-reviewed historical ledger of completed feature work and its core code snippets.
- `project/android-draft-eagle-runtime-gap.md`
  Use this when you want the current gap analysis between the Android draft runtime and an EAGLE-style branch-aware draft runtime.
- `project/android-draft-runtime-probe-demo.md`
  Use this when you want the standalone probe demo for testing Android-side draft logits extraction and runtime state round-tripping.
- `archive/2026-04-01-android-branch-expanded-draft-tree.md`
  Use this when you want the short node record for the first branch-expanded Android draft tree built from native runtime snapshots.
- `archive/2026-04-01-unified-real-token-space-plan.md`
  Use this when you want the short planning note that records why mixed token-space `p/q` acceptance regressed and why the next mainline is unified real `llama_token` ids.
- `archive/2026-04-01-real-token-draft-api-skeleton.md`
  Use this when you want the short node record for the first parallel Android draft APIs that expose real token ids without removing the legacy speculative baseline.
- `archive/2026-04-01-real-token-verifier-mode-wiring.md`
  Use this when you want the short node record for the first end-to-end experimental verifier mode that switches the Android speculative loop onto the new real-token draft APIs.
- `archive/2026-04-01-experimental-real-token-pq-verifier.md`
  Use this when you want the short node record for the first experimental verifier node that actually performs per-token `p/q` acceptance on the real-token lane.
- `environment/desktop-gguf-runtime-supplement.md`
  Use this when you want to validate a GGUF on the computer or try running it outside Android.
- `workflow/collaboration-rules.md`
  Use this when checking build, git-sync, and bundle responsibilities.
  It now also records the current Windows fallback for git commands when `git` is not on the shell `PATH`.

## Document Guide

- `docs/README.md`
  The index of the library. Start here when you do not know which document to open first.
- `docs/environment/desktop-gguf-runtime-supplement.md`
  The supplemental environment record for the computer-side GGUF inspection and desktop `llama.cpp` runtime attempt.
- `docs/project/current-status.md`
  The shortest technical handoff for what is done, what is blocked, and what the current next step should be.
- `docs/project/project-progress-summary.md`
  The milestone-level summary of all completed work so far across Android local, ordinary remote, and speculative debugging.
- `docs/project/android-local-baseline-checklist.md`
  The repeatable on-device checklist for re-confirming the Android local runtime baseline.
- `docs/project/computer-inference-service-boundary.md`
  The design boundary for the ordinary computer-hosted inference service and phone-to-computer request path.
- `docs/project/desktop-inference-service-runbook.md`
  The start/check runbook for the first local desktop HTTP inference service.
- `docs/project/speculative-decoding-protocol-draft.md`
  The first draft of the speculative decoding message set, session model, and fallback rules.
- `docs/project/speculative-decoding-implementation-guide-zh.md`
  The Chinese implementation guide that explains how speculative decoding should be built in this project.
- `docs/project/speculative-core-code-explanation.md`
  The code-focused explanation document that records the current core speculative implementation snippets and how they work.
- `docs/project/project-core-code-history.md`
  The historical core-code ledger that records completed feature nodes from git history and the key code for each one.
- `docs/project/android-draft-eagle-runtime-gap.md`
  The working assessment of what the Android draft runtime already has, what EAGLE-style draft runtime still needs, and which low-level `llama.cpp` capabilities are available for the next step.
- `docs/project/android-draft-runtime-probe-demo.md`
  The standalone probe-demo document for testing Android draft top-k probability extraction and context state save/restore outside the main speculative interface.
- `docs/archive/2026-04-01-android-branch-expanded-draft-tree.md`
  The archive note for the first Android draft-tree node that explores multiple shallow branches through native runtime snapshot/restore.
- `docs/archive/2026-04-01-unified-real-token-space-plan.md`
  The archive note that captures the new token-space conclusion: standard paper-style `p/q` acceptance now depends on unifying Android draft ids, speculative payloads, and desktop target lookup around real token ids.
- `docs/archive/2026-04-01-real-token-draft-api-skeleton.md`
  The archive note for the first experimental Android real-token draft API skeleton that now exists beside the legacy codepoint-compatible path.
- `docs/archive/2026-04-01-real-token-verifier-mode-wiring.md`
  The archive note for the first experimental verifier mode, `llama_true_tree_pq_tokens`, that now routes the Android speculative loop through the parallel real-token draft APIs.
- `docs/archive/2026-04-01-experimental-real-token-pq-verifier.md`
  The archive note for the first experimental verifier node where the real-token lane begins running its own per-token `p/q` acceptance behavior.
- `docs/workflow/collaboration-rules.md`
  The collaboration contract for git sync, Android Studio verification, the Windows git-command fallback, and the "user does bundle" boundary.
- `docs/archive/root-document-map.md`
  The bridge between the new library and the older root-level markdown records.
