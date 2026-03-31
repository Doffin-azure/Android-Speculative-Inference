# 2026-03-31 Android Speculative Stub Client

## Summary

This node connected the Android app to the first desktop speculative session stub.

The app now includes:

- a `SPECULATIVE` inference mode
- desktop speculative HTTP client calls
- one-step speculative stub execution flow in the `ViewModel`
- UI and diagnostic fields for speculative session summaries

## What Was Added

Android-side changes now cover:

- `startSession`
- `proposeDraft`
- `closeSession`

The first app-side execution shape is intentionally small:

1. open a speculative session
2. send one stub proposal using placeholder token ids derived from the prompt
3. close the session
4. show the session summary and warning in the app

## Why This Is Still A Stub

This node does not yet provide real token-level speculative decoding.

Current limitations:

- draft tokens are still placeholder ids derived from the prompt
- the desktop `propose` endpoint still accepts proposals as a lifecycle stub
- there is no real accepted-prefix verification against the desktop target model yet
- there is no real correction-token loop yet

## Why This Node Matters

This change moves the project from:

- "desktop speculative protocol and server stub exist"

to:

- "the Android app now has a concrete speculative mode and can attempt the first end-to-end session lifecycle"

That means the next node can focus on verification and then true token verification logic instead of still building UI plumbing.

## Suggested Next Node

The next node should be:

1. user-side Android Studio validation of the new speculative mode against the desktop service
2. capture one successful speculative stub session summary
3. start replacing placeholder draft-token handling and desktop stub acceptance with real token verification logic
