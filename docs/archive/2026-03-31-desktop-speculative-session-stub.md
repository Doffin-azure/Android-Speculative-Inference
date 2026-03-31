# 2026-03-31 Desktop Speculative Session Stub

## Summary

This node moved the desktop service from a speculative protocol draft to the first runnable speculative session lifecycle stub.

The new desktop-side capability now includes:

- `POST /v1/speculative/start`
- `POST /v1/speculative/propose`
- `POST /v1/speculative/fallback`
- `POST /v1/speculative/close`

These endpoints now share the existing local request log and maintain an in-memory speculative session store.

## What This Node Actually Solves

The desktop service can now:

- create a speculative session
- record draft-step proposals
- keep speculative session counters in memory
- fall back through the already proven ordinary remote generation path
- close and release speculative session state explicitly

This is enough to let the Android side begin wiring a speculative session lifecycle without needing real token verification on day one.

## Important Limitation

The current `propose` implementation is still a lifecycle stub.

It accepts and records the provided `proposedTokenIds` without yet running target-model token verification.

That means this node establishes:

- protocol shape
- session lifecycle
- logging shape
- fallback boundary

It does not yet establish:

- accepted-prefix verification against the desktop target model
- correction-token generation
- real mismatch handling

## Why This Was The Right Next Step

This keeps the project on the documented execution order:

1. prove local baseline
2. prove ordinary remote baseline
3. add the smallest speculative desktop lifecycle
4. wire the phone-side speculative state next
5. replace stub acceptance with real token verification after the loop exists end to end

## Suggested Next Node

The next node should add Android-side speculative session wiring above the existing local and ordinary remote paths while keeping ordinary remote fallback active.
