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
- `POST /v1/generate`

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

## Next Step After This Works

Once local desktop service verification succeeds:

1. add a minimal Android client for `POST /v1/generate`
2. add a simple app-level local/remote mode distinction
3. keep speculative decoding work out of scope until the ordinary remote path is stable
