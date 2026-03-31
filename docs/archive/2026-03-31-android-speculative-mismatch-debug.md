# 2026-03-31 Android Speculative Mismatch Debug

## Summary

This node improved the Android speculative debug path so correction-token behavior can be exercised directly from the device UI.

The Android app now includes:

- a force-mismatch toggle in speculative mode
- speculative result parsing for `rejectedFromIndex` and `targetTextDelta`
- richer speculative session and output summaries

## What This Changes

Before this node, the Android speculative stub path mainly demonstrated:

- session start
- draft proposal
- session close

After this node, the Android side can also deliberately trigger and display:

- accepted-prefix truncation
- rejected index reporting
- correction-token return values
- target text delta preview

## Why This Matters

This gives the project a practical regression harness for speculative protocol semantics before real target-model verification exists.

That means future desktop-side verifier changes can be tested from the phone UI without guessing whether correction behavior is wired correctly.

## Remaining Limitation

This still does not provide true token-level draft generation from the Android local model.

The next deeper implementation step remains:

- replace placeholder draft tokens with real local draft tokens
- replace desktop prompt-derived verification with actual target-model token verification
