# Computer Inference Service Boundary

## Purpose

This document defines the next implementation layer after the Android local baseline:

- a computer-side normal inference service
- a normal phone-to-computer request path

This is intentionally a non-speculative baseline.

The goal is to create the simplest stable remote path first, then layer speculative decoding on top of it later.

## Why This Comes Next

The Android local baseline has now been re-confirmed.

That means the next most valuable step is no longer Android-local debugging.

The next most valuable step is creating a clean remote boundary that:

- can be tested independently from speculative decoding
- can reuse the already validated desktop `llama.cpp` environment
- gives the phone a fallback path to a larger computer-hosted model

## Scope Of This Stage

This stage should only solve ordinary remote inference.

In scope:

- define the computer-side service contract
- define the Android client contract
- define a request/response format that works for ordinary generation
- define logging and diagnostics expectations
- choose a transport simple enough to implement and debug

Out of scope:

- speculative decoding token verification
- draft-token exchange
- advanced scheduler logic
- multi-device orchestration
- aggressive performance optimization

## Recommended First Transport

Use plain HTTP on the computer side first.

Recommended baseline:

- `POST /v1/generate` for a complete single response
- optional later upgrade to a streaming endpoint only after the non-streaming path is stable

Why this is the best first step:

- easiest to inspect with logs and manual requests
- easiest to debug separately from the Android app
- avoids adding WebSocket complexity too early
- keeps the protocol readable while the service boundary is still changing

## Recommended Response Shape

Start with one simple JSON request and one simple JSON response.

Request fields:

- `model`
- `systemPrompt`
- `userPrompt`
- `maxTokens`
- `temperature`
- `topP`
- `requestId`

Response fields:

- `requestId`
- `outputText`
- `finishReason`
- `promptTokens`
- `completionTokens`
- `totalTokens`
- `backendLabel`
- `timings`
- `error`

This is intentionally ordinary text generation, not speculative protocol traffic.

## Minimal Service Responsibilities

The computer-side service should:

1. load a configured GGUF model from the computer
2. accept a normal generation request from the phone
3. run generation through the desktop `llama.cpp` runtime
4. return a complete response with lightweight diagnostics
5. log enough request context to debug failures

The service should not yet:

1. manage multiple models dynamically unless needed
2. implement token-by-token remote verification logic
3. optimize for high concurrency before correctness is proven

## Minimal Android Client Responsibilities

The Android side should:

1. keep the existing local path intact
2. add a separate remote client path instead of replacing the local engine
3. surface clear remote status and remote error text
4. keep diagnostics copyable just like the local path

The Android app should be able to distinguish clearly between:

- local inference mode
- remote inference mode
- future hybrid/speculative mode

## Suggested Module Boundary

Keep the current local engine in `:lib`.

Add the ordinary remote client path in the app layer first unless a shared abstraction becomes clearly necessary.

Recommended early split:

- `:lib`
  local `llama.cpp` inference only
- `app`
  remote request client, mode selection, UI state, and diagnostics
- computer-side service
  separate desktop runtime process outside the Android project build

This keeps the current proven local baseline isolated from the new networked path.

## Suggested Implementation Order

Implement this stage in the following order:

1. write the service contract and example payloads
2. create the smallest possible computer-side service that returns one full response
3. verify the service locally on the computer before involving Android
4. add a minimal Android remote client for one-shot requests
5. expose a simple app-level mode switch between local and remote runs
6. only after the ordinary remote path is reliable, consider streaming or speculative upgrades

## Example Baseline Payload

```json
{
  "requestId": "test-001",
  "model": "Llama-3.2-1B-Instruct-Q4_K_M.gguf",
  "systemPrompt": "You are a concise assistant.",
  "userPrompt": "Say hello in one sentence.",
  "maxTokens": 64,
  "temperature": 0.7,
  "topP": 0.9
}
```

Example response:

```json
{
  "requestId": "test-001",
  "outputText": "Hello, I'm a concise assistant ready to help.",
  "finishReason": "stop",
  "promptTokens": 18,
  "completionTokens": 11,
  "totalTokens": 29,
  "backendLabel": "desktop-llama.cpp",
  "timings": {
    "promptMs": 120,
    "generationMs": 340
  },
  "error": ""
}
```

## Diagnostics Expectations

For the first remote baseline, always capture:

- request id
- selected model
- prompt length
- response length
- service-side error text
- Android-side error text

If a request fails, the phone and the computer service should both be able to report the same `requestId`.

## Definition Of Done For This Stage

This stage is complete when:

- the computer can run a normal inference service using the validated desktop runtime
- Android can send a normal request to that service
- Android receives a complete response and shows it clearly
- failures can be diagnosed without involving speculative-decoding logic

## What Comes After This

Only after this ordinary remote path is stable should the project define:

1. draft token proposal from phone
2. token verification by computer
3. accept/reject synchronization rules
4. fallback behavior between local-only, remote-only, and speculative modes
