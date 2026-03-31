# Speculative Decoding Protocol Draft

## Purpose

This document defines the first draft of the phone-draft / computer-verify protocol that should sit on top of the already proven baselines:

- Android local inference
- Android-to-desktop ordinary remote inference

The goal of this draft is not to optimize immediately.

The goal is to make the first speculative protocol:

- understandable
- testable
- debuggable
- easy to fall back from

## Baseline Assumptions

The protocol is built on top of these already established facts:

- the phone can run a local GGUF model
- the computer can run a larger model through the desktop service
- the phone can reach the computer over the LAN
- the phone can already send a normal remote request and receive a complete response

Therefore the speculative layer should be treated as an overlay on top of a known-good ordinary remote path, not as a replacement for it.

## High-Level Roles

Phone role:

- runs the smaller draft model locally
- proposes the next chunk of candidate tokens
- applies accepted tokens immediately
- falls back safely when verification disagrees

Computer role:

- runs the larger target model
- verifies the phone proposal
- returns the accepted prefix length
- supplies corrective tokens when needed

## First-Draft Design Principles

Use these rules for the first implementation:

1. prefer correctness over speed
2. keep chunk sizes small and explicit
3. make every request traceable with a request or session id
4. allow the protocol to fall back to ordinary remote generation at any time
5. never require hidden state that cannot be reconstructed from logs

## Session Model

Each speculative run should have a `sessionId`.

The session groups together:

- prompt initialization
- draft proposals
- verification responses
- fallback events
- final completion

The phone and computer should both log the same `sessionId`.

## Recommended First Message Set

Start with these message types only:

1. `startSession`
2. `proposeDraft`
3. `verifyDraft`
4. `fallbackGenerate`
5. `closeSession`

This is intentionally small.

Do not add advanced control messages until the basic loop works.

## Message 1: `startSession`

Purpose:

- initialize shared session state on the computer
- bind the request to a specific model and prompt prefix

Suggested payload:

```json
{
  "type": "startSession",
  "sessionId": "sess-001",
  "requestId": "req-001",
  "targetModel": "desktop-target-model",
  "draftModel": "android-draft-model",
  "systemPrompt": "You are a concise assistant.",
  "userPrompt": "Explain speculative decoding simply.",
  "sampling": {
    "temperature": 0.7,
    "topP": 0.9
  }
}
```

Suggested response:

```json
{
  "type": "startSessionResult",
  "sessionId": "sess-001",
  "status": "ready",
  "error": ""
}
```

## Message 2: `proposeDraft`

Purpose:

- send a small candidate token chunk from the phone

Suggested payload:

```json
{
  "type": "proposeDraft",
  "sessionId": "sess-001",
  "draftStep": 3,
  "proposedTokenIds": [1287, 338, 264],
  "proposedText": "speculative decoding is",
  "maxCorrectionTokens": 8
}
```

Notes:

- include token ids as the protocol source of truth
- include text as debugging support only
- keep the first draft chunk size small, for example 1 to 4 tokens

## Message 3: `verifyDraft`

In the first implementation, this can be folded into the response to `proposeDraft`.

Suggested response payload:

```json
{
  "type": "verifyDraftResult",
  "sessionId": "sess-001",
  "draftStep": 3,
  "acceptedCount": 2,
  "acceptedTokenIds": [1287, 338],
  "rejectedFromIndex": 2,
  "correctionTokenIds": [991],
  "targetTextDelta": "speculative decoding works",
  "finishReason": "",
  "error": ""
}
```

Interpretation:

- `acceptedCount` tells the phone how much of its proposal to keep
- `correctionTokenIds` gives the phone the verified next token(s) when the draft diverges
- `targetTextDelta` is helpful for diagnostics and early UI mirroring

## Message 4: `fallbackGenerate`

Purpose:

- abandon speculative stepping temporarily or fully
- continue through the already proven ordinary remote path

Use this when:

- repeated mismatches make speculation ineffective
- session state becomes inconsistent
- draft model output becomes unusable
- the phone requests a safe recovery path

Suggested payload:

```json
{
  "type": "fallbackGenerate",
  "sessionId": "sess-001",
  "reason": "verification_mismatch_threshold",
  "remainingMaxTokens": 96
}
```

## Message 5: `closeSession`

Purpose:

- release per-session state on the computer
- mark completion or early termination explicitly

Suggested payload:

```json
{
  "type": "closeSession",
  "sessionId": "sess-001",
  "reason": "completed"
}
```

## First-Draft State Machine

Phone-side state:

1. `Idle`
2. `StartingSession`
3. `Drafting`
4. `WaitingForVerification`
5. `ApplyingAcceptedTokens`
6. `FallingBack`
7. `Completed`
8. `Error`

Computer-side state:

1. `Idle`
2. `SessionReady`
3. `VerifyingDraft`
4. `ReturningCorrection`
5. `FallbackGenerating`
6. `Completed`
7. `Error`

## Acceptance Rules

For the first version:

1. the computer compares the phone proposal against the target model continuation
2. the computer returns the length of the accepted prefix
3. the phone commits only the accepted prefix
4. if the proposal diverges, the phone appends the correction from the computer
5. the next step starts from the corrected shared prefix

This should be deterministic enough to debug, even if it is not yet optimal.

## Chunk Size Guidance

Start small.

Recommended first values:

- proposed draft chunk: 1 to 4 tokens
- correction chunk: 1 token at first

Why:

- easier to reason about mismatches
- easier to debug session logs
- easier to compare phone and computer state

Only increase chunk size after correctness is stable.

## Diagnostics Requirements

Every speculative step should log:

- `sessionId`
- `draftStep`
- proposed token ids
- accepted count
- correction token ids
- fallback reason if any
- cumulative accepted token count

Minimum useful debugging rule:

- either side should be able to reconstruct the session from logs alone

## Fallback Rules

The system must be able to fall back safely to ordinary remote generation.

Fallback should happen when:

- speculative verification fails repeatedly
- session state is lost or corrupted
- a protocol version mismatch appears
- the phone draft engine becomes unavailable

Fallback modes:

1. `remote_only`
2. `local_only`
3. `ordinary_remote_resume`

The first implementation only needs `ordinary_remote_resume`.

## Recommended Transport For First Speculative Draft

Keep using HTTP first if possible.

Recommended first approach:

- `POST /v1/speculative/start`
- `POST /v1/speculative/propose`
- `POST /v1/speculative/fallback`
- `POST /v1/speculative/close`

Why HTTP first:

- reuses the already proven network path
- easier to log and replay than a long-lived socket at this stage
- keeps message semantics explicit

Move to a streaming or persistent connection only if HTTP round-trip overhead becomes the real blocker.

## Versioning

Add a protocol version from the beginning.

Suggested field:

- `protocolVersion: 1`

This avoids ambiguity later when message formats evolve.

## Definition Of Done For The First Speculative Protocol Node

The next protocol-design node is complete when:

- the message set is fixed clearly enough to implement
- the session state model is fixed clearly enough to log and debug
- the fallback path is explicit
- both the phone and computer responsibilities are unambiguous

## What To Implement After This Draft

Implementation should proceed in this order:

1. add speculative session endpoints to the desktop service
2. add phone-side speculative session state in the app layer
3. wire draft-token production from the local model
4. wire verification responses from the desktop service
5. keep ordinary remote fallback active throughout
