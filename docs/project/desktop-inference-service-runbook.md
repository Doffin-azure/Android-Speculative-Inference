# Desktop Inference Service Runbook

## Purpose

This runbook explains how to start and sanity-check the first computer-side normal inference service.

The service is currently implemented as:

- a small Python HTTP server
- calling desktop `llama-cli` through `wsl.exe`
- returning one complete JSON response per request

## Current Script

Service entry point:

- `tools/desktop_inference_service.py`

Endpoints:

- `GET /health`
- `GET /probe`
- `POST /v1/generate`
- `POST /v1/speculative/start`
- `POST /v1/speculative/propose`
- `POST /v1/speculative/fallback`
- `POST /v1/speculative/close`

## Preconditions

Before starting the service:

1. the desktop `llama.cpp` CLI build must already exist in WSL
2. the target GGUF file must already be available on the computer
3. `gradle-local.properties` should already point to the local `llama.cpp` checkout

This script uses that local path to derive the default WSL `llama-cli` location.

## Configuration Check

Run this first from the repository root:

```powershell
python tools\desktop_inference_service.py --check
```

Expected result:

- the model path is printed
- the derived `llama-cli` WSL path is printed
- `configuration_check=OK`

## Start Command

From the repository root:

```powershell
python tools\desktop_inference_service.py --host 127.0.0.1 --port 8080
```

If you want the phone to reach the service over the local network later, bind a non-loopback host such as `0.0.0.0` after local verification succeeds.

## Health Check

From another PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

Expected result:

- `status` is `ok`
- `backendLabel` is `desktop-llama.cpp-wsl-cli`

## Network Probe

Use this before trying model generation from the phone:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/probe
```

Expected result:

- `status` is `reachable`
- `clientAddress` is present
- `requestLogPath` points to the local desktop request log

The service also appends a local request log line to:

- `logs/desktop-inference-service.log`

This is useful when checking whether the phone actually reached the desktop service at all.

## Example Generate Request

```powershell
$body = @{
  requestId = "test-001"
  model = "Llama-3.2-1B-Instruct-Q4_K_M.gguf"
  systemPrompt = "You are a concise assistant."
  userPrompt = "Say hello in one sentence."
  maxTokens = 64
  temperature = 0.7
  topP = 0.9
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri http://127.0.0.1:8080/v1/generate `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

Expected result:

- the response includes `requestId`
- `outputText` contains generated text
- `error` is blank

## Current Limitations

This is intentionally the smallest useful baseline.

Current limitations:

- one-shot complete response only
- no streaming endpoint yet
- no concurrency tuning
- no persistent loaded model process yet
- prompt formatting is currently simple and conservative, not a finalized chat-template layer
- the speculative endpoints currently provide a lifecycle stub, not real token verification yet

## Speculative Session Smoke Test

Use this after the normal health and probe checks:

```powershell
$startBody = @{
  protocolVersion = 1
  type = "startSession"
  sessionId = "sess-smoke"
  requestId = "req-smoke"
  draftModel = "android-draft"
  targetModel = "desktop-target"
  userPrompt = "hello"
  sampling = @{
    temperature = 0.7
    topP = 0.9
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri http://127.0.0.1:8080/v1/speculative/start `
  -Method Post `
  -ContentType "application/json" `
  -Body $startBody
```

Expected result:

- `status` is `ready`
- `fallbackAvailable` is `true`

Then send a small token proposal:

```powershell
$proposeBody = @{
  protocolVersion = 1
  type = "proposeDraft"
  sessionId = "sess-smoke"
  draftStep = 1
  proposedTokenIds = @(11, 22, 33)
  proposedText = "hello"
  maxCorrectionTokens = 1
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri http://127.0.0.1:8080/v1/speculative/propose `
  -Method Post `
  -ContentType "application/json" `
  -Body $proposeBody
```

Expected result for the current deterministic verify stub:

- when the proposed ids match the prompt-derived target prefix, `status` is `accepted_by_prompt_stub`
- when they diverge, `status` becomes `corrected_by_prompt_stub`
- `acceptedCount`, `rejectedFromIndex`, and `correctionTokenIds` now carry real verify-style semantics
- `warning` still explains that real target-model verification is not implemented yet

Finally close the session:

```powershell
$closeBody = @{
  protocolVersion = 1
  type = "closeSession"
  sessionId = "sess-smoke"
  reason = "manual_smoke_test"
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Uri http://127.0.0.1:8080/v1/speculative/close `
  -Method Post `
  -ContentType "application/json" `
  -Body $closeBody
```

Expected result:

- `status` is `closed`
- `acceptedTokenCount` reflects the accepted proposal count recorded in the stub session

## Next Step After This Works

Once local desktop service verification succeeds:

1. use the Android-side remote connectivity probe before trying full generation
2. add or validate the Android client for `POST /v1/generate`
3. keep speculative decoding work out of scope until the ordinary remote path is stable
