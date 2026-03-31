# Desktop Inference Service Skeleton - 2026-03-31

## Completed In This Node

- added `tools/desktop_inference_service.py` as the first computer-side HTTP inference service skeleton
- added `docs/project/desktop-inference-service-runbook.md` with start, health-check, and generate-request instructions
- verified the service locally with a successful `GET /health` and `POST /v1/generate` smoke test

## Why This Matters

- the project now has a working ordinary remote baseline on the computer side
- the next implementation step can move to the Android client instead of staying in service-design mode
- speculative decoding remains correctly deferred until the normal remote path works end to end

## Recommended Resume Point

Resume from `docs/project/current-status.md`, then use `docs/project/desktop-inference-service-runbook.md` while adding the Android-side remote client.
