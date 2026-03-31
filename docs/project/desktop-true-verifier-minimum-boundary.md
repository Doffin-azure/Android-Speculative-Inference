# Desktop True Verifier Minimum Boundary

## Purpose

This document fixes the minimum implementation boundary for the first real desktop-side target verifier.

It exists to answer one practical question:

- what is the smallest thing we can build next that counts as real target verification instead of another proxy layer

## Current Position

The desktop verifier ladder already exists:

1. `prompt_stub`
2. `llama_preview`
3. `llama_step_proxy`
4. `llama_replay_proxy`

These stages are useful, but they are all still proxy stages.

The service now explicitly treats them as:

- `verifierStage = proxy_target`

The next stage must cross the line into:

- `verifierStage = true_target`

## Minimum True-Verifier Boundary

The first real verifier should satisfy all of these at once:

1. keep the existing HTTP protocol surface
2. keep ordinary remote fallback available
3. keep Android draft production stubbed for now
4. move only the desktop verifier from proxy behavior to real target behavior
5. verify against target-model continuation state, not preview text
6. support small chunks only at first
7. support correction size `1` token first

This means the next real node is desktop-only in spirit, even if Android remains the regression client.

## What Must Stay The Same

Do not change these yet:

- `POST /v1/speculative/start`
- `POST /v1/speculative/propose`
- `POST /v1/speculative/fallback`
- `POST /v1/speculative/close`
- `acceptedCount`
- `rejectedFromIndex`
- `correctionTokenIds`
- Android speculative debug UI
- existing fallback behavior

The goal is to swap the verifier engine, not to restart the protocol.

## What Must Change

The desktop verifier must stop depending on:

- prompt-derived token ids
- fixed preview text
- refreshed preview text
- replay-generated proxy text

Instead, it must hold a real target-side continuation state and answer:

- how many proposed tokens are accepted
- what the next corrective token is when divergence appears

## Minimum Runtime Shape

The first real target verifier should introduce a persistent desktop-side target session concept.

At minimum, that target session needs:

- prompt initialization
- accepted shared prefix state
- the ability to continue from the current prefix without replaying the whole prompt every step

That does not yet require streaming or multi-client optimization.

It does require that verification is no longer simulated through text proxies.

## Recommended First Scope

The smallest acceptable first real verifier is:

1. desktop-only persistent target session
2. one speculative session maps to one target verifier session
3. one proposal step verifies only a small chunk
4. one mismatch returns one correction token
5. ordinary fallback remains available when verifier state fails

## What Does Not Belong In The Next Node

Do not mix these into the next node:

- Android real local draft token production
- chunk-size optimization
- streaming transport
- speculative performance tuning
- multi-model scheduling

Those come later.

## Definition Of Done

The first real desktop verifier node is complete when:

- desktop `propose` no longer uses proxy text as the source of truth
- desktop `propose` reports `verifierStage = true_target`
- Android can still drive the path through the current speculative regression client
- correction-path and happy-path behavior both still produce readable diagnostics
- fallback remains available

## Current Next Step

The next implementation step should be:

1. keep the current Android multi-step speculative loop as the regression client
2. add the first persistent target-session boundary on desktop
3. switch desktop verification from replay proxy behavior to true target behavior
