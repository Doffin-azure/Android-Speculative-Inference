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
- `project/android-local-baseline-checklist.md`
  Use this when rerunning the proven Android local model-load and generation baseline on device.
- `project/computer-inference-service-boundary.md`
  Use this when starting the next stage above the local baseline: the ordinary computer-side inference service.
- `project/desktop-inference-service-runbook.md`
  Use this when starting and sanity-checking the first desktop HTTP inference service.
- `environment/desktop-gguf-runtime-supplement.md`
  Use this when you want to validate a GGUF on the computer or try running it outside Android.
- `workflow/collaboration-rules.md`
  Use this when checking build, git-sync, and bundle responsibilities.

## Document Guide

- `docs/README.md`
  The index of the library. Start here when you do not know which document to open first.
- `docs/environment/desktop-gguf-runtime-supplement.md`
  The supplemental environment record for the computer-side GGUF inspection and desktop `llama.cpp` runtime attempt.
- `docs/project/current-status.md`
  The shortest technical handoff for what is done, what is blocked, and what the current next step should be.
- `docs/project/android-local-baseline-checklist.md`
  The repeatable on-device checklist for re-confirming the Android local runtime baseline.
- `docs/project/computer-inference-service-boundary.md`
  The design boundary for the ordinary computer-hosted inference service and phone-to-computer request path.
- `docs/project/desktop-inference-service-runbook.md`
  The start/check runbook for the first local desktop HTTP inference service.
- `docs/workflow/collaboration-rules.md`
  The collaboration contract for git sync, Android Studio verification, and the "user does bundle" boundary.
- `docs/archive/root-document-map.md`
  The bridge between the new library and the older root-level markdown records.
