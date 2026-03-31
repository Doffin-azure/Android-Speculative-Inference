# Android Remote Client Path - 2026-03-31

## Completed In This Node

- added `RemoteInferenceClient.kt` for ordinary `POST /v1/generate` requests
- added a local/remote mode switch and remote service URL input to the app UI
- updated the app manifest for network access and cleartext HTTP during the current local-network development phase

## Why This Matters

- the Android app now has the minimum client-side path needed to talk to the working desktop inference service
- the local Android path remains available as a fallback while remote validation proceeds
- the next node can focus on Android Studio and device verification instead of more client scaffolding

## Recommended Resume Point

Resume from `docs/project/current-status.md`, start the desktop service from `docs/project/desktop-inference-service-runbook.md`, and validate the app in remote mode.
