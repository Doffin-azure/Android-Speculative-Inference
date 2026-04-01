# 2026-04-01 Unified Real Token Space Plan

## What Was Confirmed

- Android local draft runtime can now build a branch-expanded draft tree with node identities, best-path nodes, and per-node probabilities.
- The desktop `llama_true_tree` verifier can now consume that draft-tree payload during real Android-to-desktop speculative runs.
- Desktop candidate parsing no longer has to collapse every token piece to its first character; piece-aware comparison can now produce natural fragments such as `I'm just`.
- The verifier now also exposes first-pass probability diagnostics:
  - `p`
  - `q`
  - `accP`
  - `draw`
  - `pqAccepted`

## New Problem Exposed

- A direct paper-style per-token `p/q` acceptance implementation regressed behavior under the current mixed token-space protocol.
- The current system still mixes:
  - Android codepoint-compatible draft ids
  - desktop token-piece target candidates
- Under that mixed representation, leading spaces can align, but later draft tokens quickly fall out of the target candidate space.
- This causes a per-token `p/q` gate to accept only early easy tokens and then collapse back toward space-heavy corrections.

## Main Interpretation

- The blocker is no longer "how to compute `p/q` at all".
- The blocker is now "how to compute `p/q` for the same token id in the same token space".
- EAGLE avoids this by operating in one token space by default, or by using an internal draft-to-target vocab mapping before posterior evaluation.

## Next Mainline

The next mainline is now:

1. move Android draft output to real `llama_token` ids
2. move speculative payloads to real token ids
3. move desktop target lookup to token-id keyed probability lookup
4. add a new experimental verifier mode for unified-token `p/q`
5. keep the current `llama_true_tree` piece-aware path as the regression baseline until the real-token path is stable

## Why This Matters

- The project has already proved:
  - draft-tree production
  - draft-tree transport
  - desktop draft-tree-aware verification
  - first-pass probability diagnostics
- The next implementation risk is no longer speculative-session lifecycle or draft-tree visibility.
- The next real engineering risk is token-space unification.
