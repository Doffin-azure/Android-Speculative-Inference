# 2026-04-01 Experimental Real-Token `p/q` Verifier

This note records the point where the experimental speculative lane stopped being only a wiring skeleton and started running its own token-native verifier behavior.

## What Landed

- `llama_true_tree_pq_tokens` now has a dedicated desktop verifier function instead of reusing the legacy piece-prefix tree verifier.
- The experimental verifier now:
  - reads target top-k token ids directly from llama-server
  - uses llama-server `/tokenize` and `/detokenize` to keep the real-token lane out of character-space rendering
  - performs per-token `p/q` acceptance on real token ids
  - rejects at the first failed token
  - appends one target follow-up token when all proposal tokens in a step are accepted
- Android diagnostics now surface:
  - `tokenMode`
  - `acceptanceMode`

## Why This Matters

Before this node:

- the project had a parallel real-token draft API
- the project had a separate experimental verifier mode
- but the desktop verifier still mostly reused the mixed-space tree verifier core

After this node:

- the experimental lane now has its own acceptance semantics
- the verifier boundary is more honestly token-native
- debugging runs can clearly tell whether they are on:
  - `codepoint_legacy + piece_prefix`
  - or
  - `real_token + token_pq`

## What Is Still Not Done

- `p(x)` is still approximated from the currently available target top-k candidates
- correction is still a simple target-best-token fallback, not `max(p-q)` resampling
- the target runtime is still driven through the current Python + llama-server replay/tree flow, not a fuller KV-aware persistent verifier runtime
- the old mixed-space tree code still shares structural pieces with the experimental lane

## Practical Meaning

This node should be treated as:

- the first real experimental end-to-end unified-token verifier step

It should not yet be treated as:

- the final paper-complete speculative decoding implementation
