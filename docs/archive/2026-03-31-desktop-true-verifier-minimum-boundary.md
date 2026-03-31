# 2026-03-31 Desktop True Verifier Minimum Boundary

## Summary

This node does not implement true target-model token verification yet.

Instead, it fixes the minimum implementation boundary for the next real desktop verifier node and adds an explicit `verifierStage` concept to the desktop service.

## What Changed

- `tools/desktop_inference_service.py` now exposes an explicit verifier-stage concept
- proxy modes are now grouped under:
  - `verifierStage = proxy_target`
- the next real desktop verifier node is expected to switch that stage to:
  - `verifierStage = true_target`
- a new project document now defines the minimum acceptable boundary for the first real desktop verifier:
  - `docs/project/desktop-true-verifier-minimum-boundary.md`

## Why This Matters

By this point the project already had several working speculative verifier proxies.

The next step is no longer "make another proxy."

The next step is "cross the line into real target verification without destabilizing the existing protocol and Android regression client."

This node makes that transition easier because:

- the service now has an explicit stage label
- the minimum real-verifier scope is frozen in writing
- the next node can focus on implementation rather than renegotiating scope

## New Current Position

The project now has:

1. desktop proxy verifier ladder through `llama_replay_proxy`
2. Android multi-step speculative regression client
3. replay-session text state
4. a written minimum boundary for the first real desktop verifier

The next technical step remains:

- replace replay-based proxy verification with real target-model token verification
