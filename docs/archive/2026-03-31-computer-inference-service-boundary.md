# Computer Inference Service Boundary - 2026-03-31

## Completed In This Node

- recorded that the Android local baseline has been re-confirmed
- added `docs/project/computer-inference-service-boundary.md` as the next-stage design reference
- updated the project status so the active mainline now points to the ordinary computer-side inference service

## Why This Matters

- the project now has a clean handoff from Android-local validation into the first phone-to-computer architecture layer
- the next implementation step is explicitly ordinary remote inference, not speculative decoding yet
- the proven Android local path remains available as a fallback baseline while the remote path is introduced

## Recommended Resume Point

Resume from `docs/project/current-status.md`, then use `docs/project/computer-inference-service-boundary.md` to implement the first desktop service contract.
