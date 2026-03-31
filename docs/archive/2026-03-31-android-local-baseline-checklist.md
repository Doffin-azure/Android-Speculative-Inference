# Android Local Baseline Checklist - 2026-03-31

## Completed In This Node

- added a repeatable on-device checklist at `docs/project/android-local-baseline-checklist.md`
- linked the new checklist from `docs/README.md`
- updated `docs/project/current-status.md` so the next-node guidance points to the checklist directly

## Why This Matters

- the current Android local-runtime milestone now has a concrete rerun procedure
- the user can validate the baseline in Android Studio without reconstructing the steps from archive history
- future runtime regressions should now be easier to capture and compare against the known-good path

## Recommended Resume Point

Use `docs/project/current-status.md` first, then run the on-device procedure from `docs/project/android-local-baseline-checklist.md`.
