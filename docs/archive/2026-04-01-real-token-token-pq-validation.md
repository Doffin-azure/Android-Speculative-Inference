# 2026-04-01 Real-Token `token_pq` Validation

## What Was Confirmed

The experimental verifier lane now has a first real end-to-end device validation with all of these true at once:

- `verifierMode=llama_true_tree_pq_tokens`
- `tokenMode=real_token`
- `acceptanceMode=token_pq`
- Android sent real-token draft ids and real-token draft-tree metadata
- desktop verified and advanced on the same real token ids

## Representative Outcome

The successful run produced:

- committed token ids: `358, 2846, 3815, 1664, 11, 9901, 499, 369`
- committed text: ` I'm doing well, thank you for`

This matters because the system is no longer limited to:

- codepoint-compatible draft ids
- piece-prefix acceptance only
- character-rendering-based text reconstruction

## What The Step Trace Showed

1. Step 1 rejected the first Android draft token and corrected into the target token that renders as leading ` I`.
2. Step 2 accepted the first real draft token, rejected the next one, and corrected into the target-side `doing`.
3. Step 3 accepted four real draft tokens under `token_pq` and then appended a target follow-up token (`for`).

## Why This Node Matters

This is the first proof that the project's experimental speculative lane can now do all of the following in one run:

- compare Android and desktop tokens in a shared real-token space
- compute `p`, `q`, `accP`, and `pqAccepted` on that space
- accept and reject on token ids instead of on projected characters
- render the final accepted text through token-native detokenization

## Remaining Gap

This is still not the final paper-style verifier because:

- `p(x)` still comes from shallow observed top-k lookup instead of full logits
- rejection correction now uses an observed-top-k residual approximation, not a full-vocabulary `max(p-q, 0)` sample
- the verifier still depends on the current Python replay/tree driver instead of a more persistent target-runtime session
