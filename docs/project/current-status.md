# Current Project Status

## Project Goal

The long-term goal is a phone + computer cooperative speculative decoding system.

The staged path remains:

1. stabilize Android local runtime
2. validate real model load and minimal prompt generation on device
3. add a computer-side normal inference service
4. add a normal phone-to-computer path
5. build speculative decoding on top of that baseline

## Current Effective Stage

Current real stage:

- `llama.cpp` Android native build is already integrated and successful
- on-device local runtime validation has now succeeded for the current test model
- the Android local baseline has been re-confirmed through the repeat validation checklist
- the immediate blocker is no longer "can Android load and run a real model locally"
- the project now has a first working desktop HTTP inference service skeleton
- the Android app now contains a first normal remote client path and local/remote mode switch
- the project now also has a dedicated remote connectivity probe path with desktop-side request logging
- the Android-to-desktop normal remote path has now completed a successful end-to-end validation run
- the project now has a first draft of the speculative decoding protocol
- the desktop service now exposes a first speculative session lifecycle stub on top of the proven local and ordinary remote baselines
- the Android app codebase now contains a first speculative mode wired to that desktop lifecycle stub
- the desktop `propose` path now computes accepted prefixes and correction tokens through a deterministic prompt-derived verify stub
- the Android speculative mode now includes a force-mismatch debug path so correction-token behavior can be exercised from the device UI
- the desktop service now exposes an explicit speculative verifier mode so the current prompt-stub harness and a future llama-backed verifier can share the same protocol boundary
- the Android app now surfaces the active speculative verifier mode and target preview text returned by desktop session start
- the Android UI now also surfaces the active speculative verifier mode directly outside the session summary so verifier-mode changes are easier to spot during testing
- the `llama_preview` verifier mode now uses llama preview text to drive accepted/correction semantics during `propose`
- the desktop service now also exposes a `llama_step_proxy` verifier mode that refreshes llama preview text on demand when a proposal needs more target coverage
- the desktop service now also exposes a `llama_replay_proxy` verifier mode that replays the already accepted assistant prefix back into llama-cli before verifying the next proposal chunk
- the Android speculative stub client now runs a short multi-step session loop instead of stopping after a single `propose`
- the desktop speculative session now also persists explicit `acceptedText`, `lastReplayPrompt`, and `lastTargetTextDelta` state for replay-based verifier debugging
- the replay verifier now prefers explicit `acceptedText` over token-id debug reconstruction when building the next replay prompt, and the Android diagnostics now surface that replay-session state
- the first minimum boundary for a real desktop target verifier is now written down so the next implementation node can switch verifier stage without reopening protocol design
- the desktop service now keeps a separate internal target-session state object alongside each speculative session, so verifier-state continuity is no longer fully implicit inside the speculative session record
- the desktop verifier now reads and refreshes target proxy text through the dedicated target-session state instead of treating the speculative session as the only source of verifier truth
- the desktop service now has an explicit verifier-driver shape around target sessions, so `propose` no longer hardcodes proxy verification as one monolithic block
- the desktop service now also exposes a first real verifier mode, `llama_true_step`, which uses real target-model next-token checks instead of preview-text or replay-text proxies
- the first true verifier mode no longer spends a redundant refresh call before verification and now records explicit true-verifier step state inside the desktop target session
- the first true verifier mode now also caches the latest accepted-prefix -> next-token observation inside the desktop target session so repeated checks for the same prefix do not re-query the target model
- the true verifier cache is now session-wide instead of single-entry, so previously seen prefixes can be reused across more than one speculative step
- the true verifier cache state is now exposed through a shared helper instead of repeated inline cache-selection logic, which tightens the desktop target-session boundary a little further
- the first true verifier is no longer limited to one-token proof behavior; it now fetches a small target continuation chunk and can accept more than one token from a single verifier call
- the first true verifier can now also use a configured `llama-server` backend with a fixed slot and prompt-cache reuse, which is the first step away from pure standalone `llama-cli` replay
- the Android app now also surfaces the desktop true-verifier runtime backend, server slot, and chunk-position debug fields
- the `:lib` and app local-inference layers now expose an explicit draft-session interface boundary
- the Android local runtime now also has a first real draft-session implementation that rebuilds native state from the verified assistant prefix and samples model-driven draft codepoint ids for the existing speculative wire format
- the Android local runtime now also exposes a first dynamic draft-tree proposal path that returns top-k candidate nodes with probabilities while keeping the current speculative wire protocol unchanged
- the codebase now also contains a standalone Android draft-runtime probe demo that can test top-k probability extraction and state save/restore without changing the main speculative interface
- that standalone Android draft-runtime probe demo now also prints a compact summary of the local branch-expanded draft tree, including node count and best-path node indices
- the desktop service now also exposes a first `llama_true_tree` verifier mode, which keeps the wire protocol unchanged while building a shallow target-side candidate tree from `llama-server` top-k results
- the Android speculative client can now attach an optional local draft-tree payload to `propose`, and the desktop `llama_true_tree` verifier can now consume that draft-tree metadata when scoring target-side tree overlap
- the desktop `llama_true_tree` verifier has now also been upgraded from first-character candidate projection to piece-aware candidate sequences, which removed the earlier "everything collapses to space" behavior
- the desktop `llama_true_tree` verifier can now accept multi-token proposal prefixes against a best target candidate sequence, which moved end-to-end results from pure spaces to natural fragments such as `I'm just`
- the desktop verifier now also contains a first experimental probability gate that reads `p`, `q`, `accP`, and `pqAccepted` debug fields while still running inside the old mixed token-space protocol
- the latest experiments have also confirmed a new hard boundary: standard per-token `p/q` acceptance degrades under the current codepoint/piece mixed token-space and must be postponed until Android draft, protocol, and desktop target all use unified real `llama_token` ids
- the Android `:lib` layer now also exposes a first parallel real-token draft skeleton alongside the legacy codepoint path:
  - real-token draft token generation
  - real-token draft tree generation
  - token-id detokenize/render helper
  - real-token apply-verified helper
- that new real-token path is intentionally not yet the default speculative mainline; the current app regression path still runs through the legacy wire-compatible route until protocol and desktop verifier support catch up
- the desktop service and Android app now also expose a first dedicated experimental verifier path, `llama_true_tree_pq_tokens`
- when that verifier mode is active, the Android speculative loop now switches from legacy draft APIs to the new real-token draft APIs while still leaving `llama_true_tree` untouched as the regression baseline
- the desktop experimental verifier path now also uses llama-server token ids directly at the target-candidate boundary instead of projecting candidate text back into character ids
- the same experimental verifier path now also detokenizes accepted/correction token ids through llama-server `/detokenize`, so accepted assistant prefixes on that path are no longer reconstructed from debug-only character rendering
- the experimental verifier path now also routes internal prefix advancement, target-preview debug rendering, and `lastTrueExpectedTokenText` through the same token-native tokenize/detokenize helpers, which removes another set of silent fallbacks to character rendering inside the verifier core
- the experimental verifier path now also has its own dedicated token-native acceptance function instead of reusing the legacy piece-prefix tree verifier:
  - it performs per-token `p/q` acceptance on real token ids
  - it rejects at the first failed token
  - when all draft tokens are accepted for the step, it appends one target follow-up token as correction/output continuation
- on that experimental lane, "all draft tokens accepted + one target follow-up token appended" is now treated as an accepted step instead of being mislabeled as a correction step
- when the experimental lane rejects a token, it now no longer defaults directly to target top-1:
  - it first computes an observed-top-k residual distribution `max(p-q, 0)`
  - it chooses correction from that residual distribution when available
  - only then does it fall back to target best-token correction
- Android speculative diagnostics now also surface explicit `tokenMode` and `acceptanceMode` values from desktop responses, so experimental runs can confirm they are actually on the `real_token + token_pq` lane
- the experimental verifier lane now also has an explicit fallback rule:
  - if Android does not have an active local real-token draft session, the app falls back to the legacy/stub draft path
  - if desktop does not receive a `real_token` draft tree on `llama_true_tree_pq_tokens`, it falls back to piece-prefix acceptance and reports `acceptanceMode=fallback_piece_prefix`
- the experimental unified-token lane has now also completed a first real end-to-end device validation:
  - `verifierMode=llama_true_tree_pq_tokens`
  - `tokenMode=real_token`
  - `acceptanceMode=token_pq`
  - Android draft tokens and desktop target tokens matched directly in the same real-token id space
  - the verifier accepted and corrected on real token ids and produced a natural continuation (`I'm doing well, thank you for`) instead of the earlier character/piece proxy fragments
- the next active stage is replacing replay-based proxy verification with real target-model token verification

## Active Technical Findings

Already resolved:

- app-local JNI path removed from active integration
- real `llama.cpp` Android native build works
- model directory selection improved
- SAF-selected models are copied into app-private storage before native loading
- native load diagnostics are more specific
- desktop GGUF inspection works
- desktop `llama-cli` has been built in WSL
- desktop `llama-cli` has now successfully loaded the target GGUF and generated text
- Android diagnostics can now be copied directly from the UI or pulled from a persisted app-private log file
- Android-side model-load failure has been narrowed to a backend-loading problem instead of a bad GGUF file
- Android built-in backend loading has now restored successful model loading
- Android has now completed a real minimal prompt generation with the imported GGUF model

Current strongest conclusion:

- the tested `Llama-3.2-1B-Instruct-Q4_K_M.gguf` file appears structurally valid on the computer
- the same file also runs successfully through desktop `llama.cpp`
- Android now also loads the same file successfully after switching to the built-in ggml backend path
- the earlier Android failure was specifically caused by backend-loading configuration, not by the model artifact
- the Android local baseline should now be treated as established rather than tentative
- the first desktop `POST /v1/generate` baseline is now working locally through the new service skeleton
- the codebase now has the minimum Android-side pieces needed to call that remote service
- the project now has a separate network probe path so connectivity can be tested without involving model generation
- the ordinary remote path has now also been validated from the Android device over the LAN against the desktop service
- the speculative layer now has a first explicit message-set and state-machine draft instead of only a high-level goal
- the desktop service now exposes `start / propose / fallback / close` speculative endpoints with request logging
- the current desktop speculative implementation is intentionally still a lifecycle stub and does not yet perform target-model token verification
- the Android app now has a first speculative mode, remote client calls, and diagnostic summary fields for the desktop stub session flow
- the desktop speculative `propose` step no longer accepts every proposal blindly; it now returns `acceptedCount`, `rejectedFromIndex`, and `correctionTokenIds`
- the Android app can now deliberately trigger a mismatch and surface correction-token behavior directly in the speculative debug UI
- the desktop service now reports a `speculativeVerifierMode` and can optionally prepare a llama-backed preview text while keeping the current protocol stable
- the `llama_preview` mode is no longer preview-only; it now uses preview text as the current target proxy for accepted-prefix and correction-token behavior
- the new `llama_step_proxy` mode keeps the same preview-text proxy model but can refresh the preview when `propose` needs more target text than session start originally prepared
- the new `llama_replay_proxy` mode now rebuilds target proxy text from the currently accepted assistant prefix, which is closer to true continuation verification than fixed preview text
- the Android speculative harness can now record a short accepted/correction trace across multiple draft steps in the same session
- the desktop session now keeps explicit replay-verifier state that can later map more cleanly onto a persistent target session implementation
- the desktop service now also keeps an explicit internal target-session map and returns `targetSessionId`, which establishes the first persistent target-session boundary needed before `verifierStage` can move from `proxy_target` to `true_target`
- the new target-session boundary is no longer passive bookkeeping; desktop `propose` now refreshes and rehydrates verifier target state through that target-session layer
- the current proxy verifier logic is now encapsulated behind target-session driver helpers and a dedicated verify-computation result shape, which is the direct replacement point for the first true verifier
- the first true verifier node now exists as `llama_true_step`; it keeps the HTTP protocol stable while moving `verifierStage` to `true_target`
- the current true verifier now also records call count and last expected token state, which improves desktop-side debugging before a persistent target runtime session exists
- the current true verifier can now route chunk fetches through `llama-server` `/completion`, so desktop-side true verification is no longer limited to repeated standalone `llama-cli` invocations
- the Android-side debug harness can now expose whether true verification is using `llama-cli` replay or a `llama-server` slot-backed runtime
- the codebase now has an explicit local draft-session boundary (`supportsDraftSession / startDraftSession / draftNextTokenIds / applyVerifiedTokens / closeDraftSession`)
- that draft-session boundary now has a first real implementation in the Android local runtime, although it still returns codepoint-compatible draft ids instead of true libllama token ids
- the Android local runtime can now also emit a branch-expanded dynamic draft-tree structure with per-node probabilities for `llama_true_tree`, using local runtime snapshot/restore and last-token replay to explore multiple shallow branches while still keeping codepoint-compatible ids
- that branch-expanded Android draft tree now also returns explicit node identities, cumulative branch scores, and best-path node indices, which is the first real branch-object skeleton on the draft side
- a separate draft-runtime probe demo now exists to validate top-k probability extraction and context state round-tripping before any branch-aware production runtime is attempted
- the new `llama_true_tree` verifier now uses target-side top-k candidates from `llama-server` to score a shallow best path and map that result back into the existing accepted/correction protocol
- that tree verifier no longer relies on first-character projection for candidate comparison; it now keeps full candidate token-id sequences on the desktop side, which fixed the earlier "leading-space collapse" failure mode
- the Android draft tree is now proven to arrive at the desktop verifier during real device speculative runs, and the desktop debug output now surfaces draft-tree node counts, best-path nodes, overlap, and first-pass `p/q` acceptance diagnostics
- the current best end-to-end behavior under `llama_true_tree` is now a piece-aware acceptance path that can produce natural fragments such as `I'm just` from the Android draft tree plus desktop target verification
- the newest experimental blocker is now explicit: a paper-style per-token `p/q` gate cannot yet replace piece-aware acceptance because the project still mixes codepoint-compatible wire ids on Android with token-piece target candidates on desktop
- the next durable route is therefore no longer "keep tweaking the mixed-space verifier"; it is unifying Android draft production, speculative payloads, and desktop target lookup around real `llama_token` ids
- the first desktop-side move on that durable route is now in place on the experimental verifier path:
  - target top-k candidates read llama-server `id` fields directly
  - chunk-fallback tokenization can use llama-server `/tokenize`
  - accepted assistant prefixes can be rendered through llama-server `/detokenize`
- the remaining gap on that experimental path is that the internal tree-computation logic still largely reuses the old mixed-space structure and has not yet become a fully token-native verifier end-to-end
- that remaining gap is now narrower than before: the main unresolved work has shifted from token/text conversion seams to the acceptance algorithm and tree-state logic itself
- the main remaining gap is that this experimental token-native acceptance path still uses a shallow top-k lookup approximation for `p(x)` and still depends on the current Python-side replay/tree driver instead of a fuller persistent target runtime
- the latest successful `real_token + token_pq` run also clarifies the next concrete correction-side gap:
  - observed-top-k residual correction is now wired in
  - but follow-up / correction still uses only the currently observed top-k slice instead of a fuller target residual over the whole vocabulary
  - so the experimental lane is now past token-space unification failure, and the next pressure point is improving `p(x)` completeness and residual correction fidelity
- the experimental verifier lane now also aggregates target probabilities across all observed top-k candidates that share the same first real token id, which makes `p(x)` less brittle when llama-server exposes several candidate continuations beginning with the same token
- the same experimental lane now also widens its target top-k observation window beyond the ordinary branch factor, so `p(x)` lookup and observed-top-k residual correction are no longer constrained to the very narrow tree-expansion budget used by the legacy verifier
- the experimental verifier lane now also conditions draft-side `q(x)` on the current accepted draft branch context:
  - it tracks the active draft parent node while tokens are accepted
  - it first reads `q` from that parent node's children at the next depth
  - only if branch context is unavailable does it fall back to the whole draft depth

## Important Files

Android runtime path:

- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt`
- `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`
- `app/src/main/java/com/example/myapplication/ui/MainScreen.kt`
- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

Desktop GGUF validation path:

- `tools/gguf_check.py`
- `tools/desktop_inference_service.py`
- `.venv-gguf/` (ignored)
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp`
- `C:\Users\JXZ\AndroidStudioProjects\llama.cpp\build-wsl-cli`
- `logs/desktop-inference-service.log` (local, ignored)

## Current Blockers

Primary blocker:

- the next blocker is no longer Android local correctness
- the next blocker is no longer basic phone-to-computer reachability
- the next blocker is no longer the absence of desktop speculative endpoints
- the next blocker is no longer the absence of speculative verify semantics
- the next blocker is no longer the lack of a llama-backed target proxy
- the next blocker is no longer static llama preview coverage
- the next blocker is no longer replay-free target continuation
- the next blocker is no longer the absence of a desktop target-session boundary
- the next blocker is no longer the absence of any true verifier mode
- the next blocker is strengthening the new `llama-server`-backed true verifier path beyond prompt-cache reuse and shallow target-side tree scoring toward a fuller persistent target runtime session implementation
- the next blocker after that is upgrading the new Android local draft runtime from codepoint-compatible draft ids to true token/runtime semantics with less replay and stronger state continuity
- the newest concrete blocker is that the current mixed token space (`codepoint-compatible` Android draft ids versus desktop token-piece candidates) prevents a stable implementation of standard paper-style per-token `p/q` acceptance
- that means the verifier can currently use probability gates only as an experimental aid; the real implementation seam has shifted to token-space unification across Android native, speculative payloads, and desktop target lookup
- the Android side now has the first experimental real-token draft APIs, but the next blocker remains wiring that real-token path through the speculative payload and desktop verifier without regressing the current tree-aware baseline
- the desktop experimental path now has token-id lookup and detokenize helpers at its boundary, so the next blocker is narrowing the remaining mixed-space assumptions inside the verifier core itself rather than at the protocol edge

Secondary blocker:

- desktop-side runtime viability is no longer a blocker; it is now a confirmed baseline for comparison

## Recommended Next Technical Step

The next step should focus on one of these:

1. keep `llama_replay_proxy` as the regression harness for desktop-side speculative verification
2. replace replay-based proxy verification with real target-model token verification
3. keep ordinary remote fallback active while the real verifier is introduced
4. migrate the mixed codepoint/piece speculative path toward unified real `llama_token` ids before re-attempting standard per-token `p/q` acceptance

## Immediate Execution Order

Use this order unless a new runtime failure appears:

1. use `docs/project/desktop-inference-service-runbook.md` as the current desktop-service reference
2. use `docs/project/speculative-decoding-protocol-draft.md` as the protocol reference
3. keep the Android speculative stub path as the regression harness
4. use the Android multi-step speculative stub loop as the regression client
5. treat `llama_replay_proxy` as the closest current verifier harness before real token verification
6. use the new desktop target-session boundary as the implementation seam for real verifier work
7. let desktop verifier state flow through target-session helpers instead of direct speculative-session mutation
8. use `llama_true_step` as the first true-target regression mode on desktop
9. strengthen that true verifier toward a persistent target runtime session, now starting from the new `llama-server` slot-backed path when available
10. once tree-aware verification is stable, unify Android draft ids, protocol payloads, and desktop target lookup on real `llama_token` ids
11. only after the first real token-space path works, re-introduce standard per-token `p/q` acceptance
12. only after the first speculative loop works, optimize chunking or transport

Practical interpretation:

- do not reopen backend-load debugging unless a fresh device run fails again
- do not jump straight into speculative decoding protocol work
- do not replace the proven local path while introducing the remote path
- use `docs/project/project-progress-summary.md` when you need the milestone-level view of everything completed so far
- use `docs/project/speculative-core-code-explanation.md` when you need the current implementation's key code snippets instead of only milestone summaries
- use `docs/project/project-core-code-history.md` when you need the historical ledger of completed feature nodes and their core code
- use `docs/project/android-draft-eagle-runtime-gap.md` when you need the current capability gap analysis for pushing the Android draft runtime toward an EAGLE-style branch-aware implementation
- use `docs/project/desktop-true-verifier-minimum-boundary.md` when deciding what the first real desktop verifier is allowed to change
- use `docs/project/computer-inference-service-boundary.md` for architecture boundaries
- use `docs/project/desktop-inference-service-runbook.md` for the working desktop-service baseline
- use `docs/project/speculative-decoding-protocol-draft.md` for the first speculative message set
- remember that the Android app currently uses ordinary HTTP, so the desktop service host must be reachable from the device or emulator
- use the probe endpoint and desktop request log first when debugging "cannot connect" failures
- treat the current local and ordinary remote paths as proven baselines, not open hypotheses

## Definition Of Done For The Next Node

The next node is complete when all of the following are true:

- the desktop verifier no longer depends on prompt-derived or preview-text proxy token ids
- the desktop `propose` path derives accepted/correction semantics from real target-model token work
- Android draft proposals, draft-tree payloads, and desktop verifier lookup all operate in the same real token-id space
- standard per-token `p/q` acceptance is performed against that unified token space instead of the current codepoint/piece bridge
- ordinary remote fallback remains available
- the Android speculative debug harness remains usable as the regression client
- the close-out includes the required git-sync explanation and markdown summary update

The current desktop proxy-verifier ladder is now complete through `llama_replay_proxy`.

The remaining completion work for this node is strengthening the first real desktop verifier beyond replay-based chunk checks and the new `llama-server` prompt-cache path toward a fuller persistent target runtime session.

## After That

Once the ordinary remote boundary is defined, the next architectural step is:

1. define the speculative draft/verify protocol
2. decide how the phone-local model and computer-hosted model exchange token work
3. preserve fallback behavior between local-only, remote-only, and future speculative modes

That protocol-definition step is now complete at the draft level.

The next implementation step is to turn it into the first real speculative session lifecycle.

That lifecycle is now in place together with prompt-derived, llama-preview, and llama-replay verifier proxies.

The next implementation step is to replace those proxies with true target-model token verification.

The Android-side regression harness is now stronger because it can exercise more than one speculative step inside a single desktop session.

The desktop-side verifier boundary is now stronger because speculative sessions and target sessions are no longer represented by only one internal object.

## Android Studio Verification Needed By User

For the next validation node:

- run one `llama_replay_proxy` speculative request and capture the session summary
- confirm the summary now shows more than one speculative step when the verifier keeps returning more target text
- keep one `llama_step_proxy` or `llama_preview` run available as a regression comparison
- once real verifier work lands, run both a happy-path and correction-path speculative request from the app
- keep one known-good ordinary remote run recorded as the fallback reference

## What Not To Reopen

Do not go back to:

- app scaffolding
- old app-local JNI path
- bundle workflow by Codex
- extra file-picker UX work unless a runtime issue requires it
