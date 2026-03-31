# Remote Connectivity Probe - 2026-03-31

## Completed In This Node

- added a dedicated `GET /probe` endpoint to the desktop inference service
- added desktop-side request logging for probe and generation requests
- added an Android-side remote connectivity probe action that records results in the existing diagnostics surfaces

## Why This Matters

- connectivity can now be checked independently from model generation
- the desktop side now records whether the Android device reached the service at all
- future "cannot connect" debugging can start from a smaller and more reliable test path

## Recommended Resume Point

Resume from `docs/project/current-status.md`, start the desktop service, run the Android-side remote probe first, and compare the result with `logs/desktop-inference-service.log`.
