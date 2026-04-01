# Project Core Code History

## Purpose

This document is the historical core-code ledger for the project.

It was created by reviewing the git history commit by commit and extracting every commit that completed a real feature instead of only updating documentation.

For each included feature node, this document records:

1. the originating commit
2. the feature that was completed
3. the core code snippet
4. a short explanation of why that snippet is the implementation core

## Selection Rule

Included:

- commits that completed a real code path, runtime behavior, service endpoint, UI capability, or verifier capability

Excluded from the main list but reviewed:

- pure documentation commits
- ignore-only commits
- pure config-template commits
- cleanup-only or refactor-only commits that did not complete a new capability by themselves

## 1. Initial App + Lib Framework

Commit:

- `8273609` `初次完成框架`

Core code:

```kotlin
interface LocalLlm {
    fun isModelLoaded(): Boolean
    fun loadModel(modelPath: String)
    fun generate(prompt: String): String
    fun release()
}
```

Why this is core:

- This was the first app-level interface that let the UI and ViewModel talk to a local model path through a stable abstraction.
- The later migration to `:lib` and official `llama.cpp` integration still depends on this separation idea.

## 2. Lib API Alignment For Later Source Switch

Commit:

- `02bf87b` `Align lib API with llama.android and prep source switch`

Core code:

```kotlin
interface InferenceEngine {
    fun isAvailable(): Boolean
    fun loadModel(modelPath: String)
    fun generate(prompt: String, onToken: ((String) -> Unit)? = null): String
    fun release()
    fun lastError(): String
}
```

Why this is core:

- This is where the internal engine boundary started to resemble the later `llama.android` style lifecycle.
- It made later source replacement possible without rewriting the whole app surface.

## 3. Local Llama Source Path Loading In Gradle

Commits:

- `b4d65ad`
- `e014dc3`
- `b2f8613`
- `2057c5f`

Core code:

```kotlin
val localProperties = Properties().apply {
    val file = rootProject.file("gradle-local.properties")
    if (file.exists()) {
        file.inputStream().use(::load)
    }
}

val llamaCppSourceDir = localProperties.getProperty("llamaCppSourceDir")
```

Why this is core:

- This is the configuration seam that allowed the project to build against a local `llama.cpp` checkout instead of baking machine-specific paths into committed Gradle files.
- Without this, the official source migration could not be made practical on the local machine.

## 4. Official `llama.android` Migration Start

Commits:

- `cbfa134`
- `90d364e`
- `a90e906`
- `988f1e5`
- `f873d54`

Core code:

```cpp
extern "C"
JNIEXPORT jlong JNICALL
Java_com_example_myapplication_llama_internal_NativeBridge_createContext(
    JNIEnv * env,
    jobject /* this */,
    jstring model_path
) {
    // create llama-backed native context instead of returning a stub handle
}
```

Why this is core:

- This was the real pivot from stub native code to the official-style native integration path.
- The project stopped pretending to have a model backend and started wiring a real native context boundary.

## 5. Remove Obsolete App-Side JNI Path

Commit:

- `662d125`

Core code:

```kotlin
// app-side JNI bridge removed from active path
// native integration now stays centered in :lib
```

Why this is core:

- This commit closed the old competing integration path.
- It matters because the current project still relies on that decision: active native integration belongs in `:lib`.

## 6. Model Directory Picker

Commit:

- `314503d`

Core code:

```kotlin
fun onModelDirectorySelected(directoryUri: Uri) {
    val modelFiles = findModelFilesInDirectory(directoryUri)
    _modelCandidates.value = modelFiles
}
```

Why this is core:

- This was the first complete user-facing model selection path through SAF.
- Later multi-model selection and model import work builds directly on this.

## 7. Multi-Model Directory Selection Flow

Commit:

- `39a2b14`

Core code:

```kotlin
data class ModelCandidate(
    val name: String,
    val contentUri: String,
    val sizeBytes: Long
)
```

Why this is core:

- This turned model selection from a single-path picker into a candidate-selection flow.
- It is the data structure that made later model copying and explicit selection possible.

## 8. Runtime Initialization And Streamed Output Handling

Commit:

- `1edca2c`

Core code:

```kotlin
localLlm.generate(prompt) { token ->
    appendGeneratedToken(token)
}
```

Why this is core:

- This is where generation was treated as an incremental runtime flow rather than only a one-shot result.
- Even though the implementation changed later, this was the first meaningful streamed-output shape in the app layer.

## 9. Native Init Failures Surfaced More Clearly

Commit:

- `6d0e235`

Core code:

```kotlin
override fun lastError(): String = NativeBridge.lastError()
```

Why this is core:

- It exposed native initialization failures back to Kotlin instead of trapping them inside the native layer.
- Later diagnostics work all depends on this error surface existing.

## 10. Import SAF-Selected Models Into App Storage

Commit:

- `88ce84e`

Core code:

```kotlin
private fun importModelToAppStorage(sourceUri: Uri): File {
    val targetFile = File(modelsDir(), buildImportedModelName(sourceUri))
    contentResolver.openInputStream(sourceUri).use { input ->
        targetFile.outputStream().use { output -> input!!.copyTo(output) }
    }
    return targetFile
}
```

Why this is core:

- This solved the real Android runtime problem that SAF URIs are not reliable native-load inputs.
- The project's successful local GGUF baseline depends on this import step.

## 11. Native GGUF Load Diagnostics

Commits:

- `61c30f9`
- `22a2c7c`
- `8cf7731`

Core code:

```cpp
static std::string g_last_error;

static void set_last_error(const std::string & message) {
    g_last_error = message;
}
```

Why this is core:

- This is the native diagnostic backbone that made later Android-side troubleshooting concrete.
- It changed failures from "load failed" to explicit backend, mmap, and file-state clues.

## 12. Copyable Diagnostics UI And Persisted Log

Commit:

- `3f0972a`

Core code:

```kotlin
private fun persistDiagnosticSnapshot() {
    val logFile = diagnosticLogFile()
    logFile.writeText(snapshot)
    _diagnosticLogPath.value = logFile.absolutePath
}
```

Why this is core:

- This made runtime diagnostics durable and shareable instead of being trapped in ephemeral UI state.
- It became the standard handoff format during repeated Android verification.

## 13. Built-In ggml Backend On Android

Commit:

- `1cd75b5`

Core code:

```cpp
// switch Android load path to built-in ggml backend
// instead of the earlier failing backend-loading route
```

Why this is core:

- This was the decisive fix that turned Android model loading from blocked to working.
- It is the reason the Android local GGUF baseline became real instead of hypothetical.

## 14. Desktop GGUF Inspection Helper

Commit:

- `4ee86da`

Core code:

```python
def read_gguf_header(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        magic = handle.read(4)
        version = int.from_bytes(handle.read(4), "little")
    return {"magic": magic, "version": version}
```

Why this is core:

- This was the first dedicated desktop-side tool that could verify whether the GGUF artifact itself looked structurally sane before blaming Android.
- It established the computer-side model artifact check path.

## 15. Desktop HTTP Inference Service Skeleton

Commit:

- `2aea848`

Core code:

```python
class InferenceRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(HTTPStatus.OK, {"status": "ok"})

    def do_POST(self) -> None:
        if self.path == "/v1/generate":
            response = run_generation(self.server.config, payload)
```

Why this is core:

- This created the first computer-side service shell.
- Everything in ordinary remote and later speculative work depends on this server existing.

## 16. Android Ordinary Remote Client Path

Commit:

- `f800bfd`

Core code:

```kotlin
val response = remoteClient.generate(
    baseUrl = baseUrl,
    request = GenerateRequest(
        userPrompt = prompt
    )
)
```

Why this is core:

- This is the first successful app-side handoff from local-only inference to desktop-hosted inference.
- It established the normal remote baseline that speculative later uses as fallback.

## 17. Remote Connectivity Probe

Commit:

- `e7f3758`

Core code:

```python
if self.path == "/probe":
    payload = {
        "status": "reachable",
        "clientAddress": self.client_address[0],
        "requestLogPath": str(self.server.config.request_log_path),
    }
```

Why this is core:

- This separated "network reachability" from "model generation".
- It became the fastest way to debug phone-to-computer failures before looking at inference logic.

## 18. Ordinary Remote Result Summary

Commit:

- `60e3c23`

Core code:

```kotlin
_remoteResultSummary.value = buildString {
    appendLine("RequestId: ${response.requestId}")
    appendLine("Finish reason: ${response.finishReason}")
    appendLine("Backend: ${response.backendLabel}")
}
```

Why this is core:

- This made remote success visible in the app without checking server logs.
- It turned the ordinary remote path into a usable baseline instead of a hidden transport.

## 19. Speculative Session Lifecycle Stub

Commit:

- `25d57e4`

Core code:

```python
if self.path == "/v1/speculative/start":
    response = start_speculative_session(self.server, payload)
elif self.path == "/v1/speculative/propose":
    response = propose_speculative_tokens(self.server, payload)
elif self.path == "/v1/speculative/close":
    response = close_speculative_session(self.server, payload)
```

Why this is core:

- This was the first time speculative became a real service lifecycle instead of only a protocol draft.
- It established `start / propose / fallback / close` as live endpoints.

## 20. Android Speculative Stub Client Mode

Commit:

- `b57126e`

Core code:

```kotlin
enum class InferenceMode {
    LOCAL,
    REMOTE,
    SPECULATIVE
}
```

Why this is core:

- This was the first app-side activation point for speculative behavior.
- It made the desktop speculative endpoints reachable from the phone UI.

## 21. Speculative Verify-Semantics Stub

Commit:

- `2645fc3`

Core code:

```python
return {
    "acceptedCount": accepted_count,
    "rejectedFromIndex": rejected_from_index,
    "correctionTokenIds": correction_token_ids,
}
```

Why this is core:

- This is where speculative verification stopped being "always accept" and started returning real accepted/correction semantics.
- Even as a stub, it made end-to-end protocol debugging meaningful.

## 22. Android Mismatch Debug Path

Commit:

- `476593b`

Core code:

```kotlin
private fun maybeMutateStubDraftTokens(tokenIds: List<Int>, draftStep: Int): List<Int> {
    if (!_speculativeForceMismatch.value) return tokenIds
    return tokenIds.mapIndexed { index, tokenId ->
        if (draftStep == 1 && index == 1) tokenId + 1 else tokenId
    }
}
```

Why this is core:

- This gave the app a deliberate way to force correction-token behavior from the UI.
- It became the quickest regression path for accepted-prefix vs correction behavior.

## 23. Verifier Mode Boundary

Commit:

- `ac7228c`

Core code:

```python
def infer_verifier_stage(verifier_mode: str) -> str:
    if verifier_mode == "prompt_stub":
        return "prompt_stub"
    if verifier_mode in {"llama_preview", "llama_step_proxy", "llama_replay_proxy"}:
        return "proxy_target"
```

Why this is core:

- This is the formal boundary between regression harness modes and future target-backed modes.
- Later preview/replay/true verifier work builds on this switch.

## 24. Android Verifier Metadata Visibility

Commits:

- `d336131`
- `ab7adc2`

Core code:

```kotlin
_speculativeVerifierMode.value = probe.speculativeVerifierMode
```

Why this is core:

- This made verifier mode visible from the phone, which is essential once multiple desktop verifier modes exist.
- It turned the Android app into an actual verifier regression client.

## 25. Llama Preview Proxy

Commit:

- `0ef3441`

Core code:

```python
if verifier_mode in {"llama_preview", "llama_step_proxy"} and target_preview_text.strip():
    return token_ids_from_text(target_preview_text)
```

Why this is core:

- This was the first verifier mode that used llama-generated text as the proxy target instead of prompt-derived token ids.
- It was the bridge from deterministic stub to model-backed proxy verification.

## 26. Llama Step Proxy

Commit:

- `c411bc4`

Core code:

```python
if current_chars < min_target_chars:
    preview_response = run_generation(...)
```

Why this is core:

- This removed the fixed-preview limitation by letting the verifier refresh more target coverage during `propose`.
- It was the first proxy mode that reacted dynamically to proposal length.

## 27. Llama Replay Proxy

Commit:

- `45ed0f6`

Core code:

```python
replay_prompt = build_replay_prompt(
    target_session.system_prompt,
    target_session.user_prompt,
    target_session.accepted_text,
)
```

Why this is core:

- This was the first proxy verifier that depended on the already accepted assistant prefix instead of only the original prompt.
- It pushed the verifier closer to real continuation checking.

## 28. Android Multi-Step Speculative Loop

Commit:

- `e326a81`

Core code:

```kotlin
private const val SPECULATIVE_STUB_MAX_STEPS = 3

repeat(SPECULATIVE_STUB_MAX_STEPS) {
    // propose, collect accepted/correction tokens, continue in same session
}
```

Why this is core:

- This turned the app from a one-step speculative smoke test into a short session-level regression client.
- It made session continuity testable.

## 29. Replay Verifier Session State

Commit:

- `6d9e982`

Core code:

```python
accepted_text: str
last_replay_prompt: str
last_target_text_delta: str
```

Why this is core:

- These fields made replay verifier state explicit instead of implied.
- They are the state fields later carried forward into the target-session design.

## 30. Replay Text State Visibility

Commit:

- `d383006`

Core code:

```kotlin
appendLine("acceptedText=${trace.acceptedText}")
appendLine("lastReplayPrompt=${trace.lastReplayPrompt}")
```

Why this is core:

- This exposed replay-session text state in Android diagnostics.
- It made desktop verifier state inspectable from the phone-side regression client.

## 31. Minimum True-Verifier Boundary In Code

Commit:

- `8b2fbc9`

Core code:

```python
"speculativeVerifierStage": infer_verifier_stage(self.server.config.speculative_verifier_mode)
```

Why this is core:

- Although the commit was primarily documentation-driven, it also made the verifier stage explicit in service responses.
- That field became the code-level flag for moving from proxy to true target verification.

## 32. Target-Session Boundary

Commit:

- `0469e7a`

Core code:

```python
self.target_sessions: dict[str, TargetSessionState] = {}
```

Why this is core:

- This is where desktop verifier state stopped living only inside speculative-session storage.
- It created the separate target-session ownership model required by later true verifier work.

## 33. Verifier Driver Boundary

Commit:

- `2e3c646`

Core code:

```python
@dataclass
class VerifyComputation:
    accepted_token_ids: list[int]
    correction_token_ids: list[int]
    rejected_from_index: int
```

Why this is core:

- This extracted the verifier engine result into a dedicated shape.
- It is the seam that let the project swap a proxy verify engine for a true verify engine.

## 34. First True Desktop Verifier

Commit:

- `4ec3a85`

Core code:

```python
if session.verifier_mode == "llama_true_step":
    computation = compute_true_verifier_result(
        server.config,
        target_session,
        accepted_token_ids=session.accepted_token_ids,
        accepted_token_count=session.accepted_token_count,
        proposed_token_ids=proposed_token_ids,
        max_correction_tokens=max_correction_tokens,
    )
```

Why this is core:

- This is the first point where desktop speculative verification became truly target-backed instead of proxy-backed.
- It moved `verifierStage` to `true_target` while keeping the protocol stable.

## 35. Server-Backed True Verifier Bridge

Commit:

- current sync node

Core code:

```python
if config.llama_server_base_url and target_session is not None and target_session.llama_server_slot_id >= 0:
    response = run_generation_from_server_completion(
        config,
        request_id=request_id,
        model=model,
        full_prompt=replay_prompt,
        max_tokens=max(1, max_tokens),
        temperature=0.0,
        top_p=1.0,
        slot_id=target_session.llama_server_slot_id,
        cache_prompt=True,
    )
    response.setdefault("debug", {})
    response["debug"]["runtimeBackend"] = "llama_server_slot"
    return response
```

Why this is core:

- This is the first point where the true verifier can use a `llama-server` slot as its target-runtime backend instead of only replaying through standalone `llama-cli`.
- It keeps the speculative protocol unchanged while moving desktop verification closer to a persistent target session shape.

## 36. Android Draft-Session Boundary

Commit:

- current sync node

Core code:

```kotlin
data class DraftSessionHandle(
    val sessionId: String,
    val runtimeLabel: String,
    val acceptedText: String = "",
    val acceptedTokenCount: Int = 0
)

fun supportsDraftSession(): Boolean = false

suspend fun startDraftSession(...): DraftSessionHandle
suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int>
suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle
suspend fun closeDraftSession(sessionId: String)
```

Why this is core:

- This is the first explicit local runtime boundary for true draft work.
- It turns Android speculative draft from an implicit future idea into a concrete code seam that later native work can implement.

## 37. Android First Local Draft Runtime

Commit:

- current sync node

Core code:

```kotlin
override suspend fun draftNextTokenIds(sessionId: String, maxTokens: Int): List<Int> = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
    resetDraftRuntime(runtime)
    generateDraftTokenIds(maxTokens).toList()
}

override suspend fun applyVerifiedTokens(sessionId: String, tokenIds: List<Int>): DraftSessionHandle = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
    val updatedRuntime = runtime.copy(acceptedText = runtime.acceptedText + codePointIdsToString(tokenIds))
    resetDraftRuntime(updatedRuntime)
    draftSessions[sessionId] = updatedRuntime
    DraftSessionHandle(
        sessionId = updatedRuntime.sessionId,
        runtimeLabel = "ai-chat draft session",
        acceptedText = updatedRuntime.acceptedText,
        acceptedTokenCount = updatedRuntime.acceptedText.codePointCount(0, updatedRuntime.acceptedText.length)
    )
}
```

```cpp
JNIEXPORT jint JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_resetDraftContext(...) {
    reset_long_term_states();
    reset_short_term_states();
    process_prompt_text(system, ROLE_SYSTEM, true);
    process_prompt_text(user, ROLE_USER, false, true);
    process_prompt_text(assistant, ROLE_ASSISTANT, false);
    stop_generation_position = current_position + std::max(1, (int) predict_length);
    return 0;
}

JNIEXPORT jintArray JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftTokenIds(...) {
    const auto new_token_id = common_sampler_sample(g_sampler, g_context, -1);
    common_sampler_accept(g_sampler, new_token_id, true);
    ...
    auto new_token_chars = common_token_to_piece(g_context, new_token_id);
    cached_token_chars += new_token_chars;
    ...
    draft_ids.push_back((jint) codepoint);
}
```

Why this is core:

- This is the first point where Android speculative proposals can come from the real local model runtime rather than only from prompt-derived stub text.
- The implementation still rebuilds native state from the verified prefix and still returns codepoint-compatible ids for wire compatibility, but it is the first real draft-runtime node in the project history.

## 38. Desktop Tree-Shaped True Verifier First Cut

Commit:

- current sync node

Core code:

```python
def fetch_target_top_candidates(...):
    response = run_generation_from_server_completion(
        config,
        request_id=f"{target_session.request_id}-true-tree-{step_index}",
        model=target_session.target_model,
        full_prompt=replay_prompt,
        max_tokens=1,
        temperature=0.0,
        top_p=1.0,
        slot_id=target_session.llama_server_slot_id,
        cache_prompt=True,
        n_probs=max(1, branch_factor),
        post_sampling_probs=True,
    )
```

```python
elif session.verifier_mode == "llama_true_tree":
    computation = compute_true_tree_verifier_result(
        server.config,
        target_session,
        accepted_token_ids=session.accepted_token_ids,
        accepted_token_count=session.accepted_token_count,
        proposed_token_ids=proposed_token_ids,
        max_correction_tokens=max_correction_tokens,
    )
```

Why this is core:

- This is the first verifier node that expands a shallow target-side candidate tree from `llama-server` top-k probabilities while keeping the current Android wire protocol unchanged.
- It is the first concrete step from linear true verification toward an EAGLE-inspired multi-candidate verifier shape.

## 39. Android First Dynamic Draft Tree Proposal

Commit:

- current working node

Core code:

```kotlin
data class DraftTreeProposal(
    val sessionId: String,
    val rootAcceptedText: String,
    val bestPathTokenIds: List<Int>,
    val bestPathText: String,
    val branchFactor: Int,
    val depthEvaluated: Int,
    val nodes: List<DraftTreeNode>
)

override suspend fun draftTreeProposal(
    sessionId: String,
    maxDepth: Int,
    branchFactor: Int
): DraftTreeProposal = withContext(llamaDispatcher) {
    val runtime = draftSessions[sessionId]
        ?: throw IllegalArgumentException("Unknown draft session: $sessionId")
    resetDraftRuntime(runtime)
    parseDraftTreeProposalJson(
        sessionId = sessionId,
        rootAcceptedText = runtime.acceptedText,
        jsonText = generateDraftTreeJson(maxDepth, branchFactor)
    )
}
```

```cpp
static std::vector<draft_tree_candidate> top_candidates_from_current_logits(int branch_factor) {
    const float *logits = llama_get_logits(g_context);
    ...
}

JNIEXPORT jstring JNICALL
Java_com_example_myapplication_llama_internal_InferenceEngineImpl_generateDraftTreeJson(...) {
    const auto candidates = top_candidates_from_current_logits(safe_branch_factor);
    const auto &best_candidate = candidates.front();
    common_sampler_accept(g_sampler, best_candidate.token_id, true);
    ...
}
```

Why this is core:

- This is the first point where the Android local draft runtime can expose per-node probabilities and a dynamic best-path tree instead of only a flat token slice.
- The implementation is still lightweight and codepoint-compatible, but it is the first Android-side speculative producer that actually reasons over next-step logits.

## 40. Android Branch-Expanded Draft Tree Runtime

Commit:

- current working node

Core code:

```cpp
static runtime_branch_snapshot capture_runtime_branch_snapshot() {
    const size_t state_size = llama_state_get_size(g_context);
    runtime_branch_snapshot snapshot {
            std::vector<uint8_t>(state_size),
            capture_host_runtime_snapshot()
    };
    const size_t saved_size = llama_state_get_data(g_context, snapshot.state_data.data(), snapshot.state_data.size());
    snapshot.state_data.resize(saved_size);
    return snapshot;
}

static bool restore_runtime_branch_snapshot(const runtime_branch_snapshot &snapshot) {
    llama_state_set_data(g_context, snapshot.state_data.data(), snapshot.state_data.size());
    ...
    return rebuild_logits_cursor_from_snapshot(snapshot.host_snapshot);
}
```

```cpp
for (const auto &branch : active_branches) {
    restore_runtime_branch_snapshot(branch.snapshot);
    const auto candidates = top_candidates_from_current_logits(safe_branch_factor);

    for (const auto &candidate : candidates) {
        restore_runtime_branch_snapshot(branch.snapshot);
        advance_runtime_with_token(candidate.token_id, candidate.token_text);

        draft_tree_branch child_branch {
                capture_runtime_branch_snapshot(),
                node_index,
                depth + 1,
                branch.cumulative_log_probability + candidate.log_probability,
                branch.path_text + candidate.token_text,
                branch.path_ids
        };
        append_utf8_codepoints(candidate.token_text, child_branch.path_ids);
        child_branch.path_node_indices = branch.path_node_indices;
        child_branch.path_node_indices.push_back(node_index);
    }
}
```

Why this is core:

- This is the first Android draft runtime node that truly expands more than one local branch from the same prefix instead of only rolling forward along top-1.
- It turns the earlier probability-bearing draft tree into a branch-aware tree producer by using native runtime snapshots plus the verified restore-and-replay rule.
- It also introduces explicit branch/node identity on the Android side, which is the first concrete skeleton for later keep/prune work.

## 41. Remote Verifier Starts Consuming Draft Tree Metadata

Commit:

- current working node

Core code:

```kotlin
data class SpeculativeProposeRequest(
    val sessionId: String,
    val draftStep: Int,
    val proposedTokenIds: List<Int>,
    val proposedText: String,
    val maxCorrectionTokens: Int = 1,
    val draftTree: DraftTreeProposal? = null
)
```

```python
draft_tree = parse_optional_draft_tree_payload(payload.get("draftTree"))
...
tree = build_true_tree_computation(
    config,
    target_session,
    target_index=target_index,
    proposed_token_ids=proposed_token_ids,
    max_correction_tokens=max_correction_tokens,
    draft_tree=draft_tree,
)
```

Why this is core:

- This is the first time the remote verifier consumes branch-aware draft-side structure instead of only a flat proposal token list.
- It does not yet implement full posterior verification, but it establishes the first real cross-device path from Android draft tree production into desktop tree-aware verification.

## 42. Desktop Candidate Projection Stops Collapsing Pieces To First Codepoints

Commit:

- current working node

Core code:

```python
def common_prefix_length(left: Sequence[int], right: Sequence[int]) -> int:
    limit = min(len(left), len(right))
    index = 0
    while index < limit and left[index] == right[index]:
        index += 1
    return index

def candidate_probability(candidate: dict[str, Any]) -> float:
    prob = float(candidate.get("prob", 0.0) or 0.0)
    if prob > 0.0:
        return prob
    logprob = candidate.get("logprob")
    if logprob is None:
        return 0.0
    return math.exp(float(logprob))
```

```python
token_ids = token_ids_from_text(token_text)
if token_ids:
    normalized_candidates.append(
        {
            "tokenId": int(token_ids[0]),
            "tokenIds": token_ids,
            "tokenText": token_text,
            "prob": prob,
            "logprob": logprob,
            "score": float(logprob if logprob is not None else math.log(max(prob, 1e-12))),
        }
    )
```

Why this is core:

- This is the node where the desktop verifier stopped treating a whole target token piece like only its first character during comparison.
- It removed the earlier failure mode where many target candidates such as `" doing"` and `" just"` collapsed into the same leading-space codepoint and forced the verifier toward meaningless space-heavy best paths.

## 43. Piece-Aware Draft-Tree Verification Starts Producing Natural Fragments

Commit:

- current working node

Core code:

```python
proposal_match_len = common_prefix_length(remaining_proposal, candidate_token_ids)
draft_path_match_len = common_prefix_length(draft_best_suffix, candidate_token_ids)
draft_overlap = len(set(candidate_token_ids) & set(draft_layer_prob_by_token.keys()))

sort_key = (
    draft_path_match_len,
    1 if draft_best_token_id == candidate_token_ids[0] else 0,
    proposal_match_len,
    1 if candidate_token_ids and candidate_token_ids[0] in draft_layer_prob_by_token else 0,
    draft_overlap,
    candidate_probability(candidate),
)
```

```python
matched_count = common_prefix_length(remaining_proposal, best_candidate_token_ids)
accepted = remaining_proposal[:matched_count]
correction = best_candidate_token_ids[matched_count:matched_count + max_correction_tokens]
```

Why this is core:

- This is the first node where the desktop verifier really used Android draft-tree metadata plus full candidate token sequences to accept meaningful proposal fragments instead of returning mostly spaces.
- It produced the first stable end-to-end behavior such as `I'm just`, which proved that the remote verifier could do more than shallow overlap logging.

## 44. Experimental Probability Gate Exposes The Mixed Token-Space Boundary

Commit:

- current working node

Core code:

```python
selected_target_prob = summed_first_token_probability(candidates, proposed_token_id)
selected_draft_prob = float(draft_prob_by_token.get(proposed_token_id, 0.0))

if selected_target_prob > 0.0 and selected_draft_prob > 0.0:
    acceptance_probability = min(1.0, selected_target_prob / selected_draft_prob)
    probability_draw = deterministic_probability_draw(
        target_session.request_id,
        target_index,
        depth,
        proposed_token_id,
    )
    pq_accepted = probability_draw <= acceptance_probability
```

Why this is core:

- This is the first end-to-end node where the verifier exposed real `p`, `q`, `accP`, `draw`, and `pqAccepted` diagnostics during live Android-to-desktop speculative runs.
- It also established an equally important negative result: standard per-token `p/q` acceptance degrades in the current system because Android draft ids are still codepoint-compatible while desktop target candidates are still token-piece based.

## 45. EAGLE Alignment Conclusion: Unify Real Token Space Before Standard `p/q`

Commit:

- current working node

Core code:

```python
elif session.verifier_mode == "llama_true_tree_pq_tokens":
    # reserved experimental path for unified real-token acceptance
    ...
```

```kotlin
data class DraftTreeNode(
    val nodeIndex: Int,
    val tokenId: Int,
    val tokenText: String,
    ...
)
```

Why this is core:

- This node is not a completed runtime feature yet; it is the project-history point where the implementation direction changed.
- After confirming EAGLE's design, the project now treats unified real `llama_token` ids as the required next mainline for standard paper-style `p/q` acceptance, rather than continuing to harden the mixed codepoint/piece bridge.

## 46. Experimental Desktop Real-Token Boundary Lands

Commit:

- current working node

Core code:

```python
if is_real_token_verifier_mode(target_session.verifier_mode):
    raw_token_id = item.get("id", -1)
    token_id = int(raw_token_id) if isinstance(raw_token_id, (int, float)) else -1
    token_ids = [token_id] if token_id >= 0 else []
```

```python
def detokenize_with_server(base_url: str, token_ids: list[int]) -> str:
    response = request_json("POST", f"{base_url}/detokenize", {"tokens": token_ids})
    return str(response.get("content") or "")
```

```python
session.accepted_text = render_token_ids_for_verifier(config, target_session, session.accepted_token_ids)
```

Why this is core:

- This is the first desktop-side implementation node where the experimental `llama_true_tree_pq_tokens` path stops projecting target candidates back into character ids and starts using llama-server token ids directly.
- It also ensures accepted/correction token ids on that path can be rendered back into assistant text through llama-server detokenization, which is necessary before replay prompts and verifier state can stay meaningful in a unified real-token lane.
- The same node now also centralizes internal verifier rendering and tokenization through shared helpers, so prefix advancement and debug state on the experimental path no longer quietly drop back into character-space semantics.

## 47. Experimental Real-Token Verifier Gets Its Own `p/q` Acceptance Loop

Commit:

- current working node

Core code:

```python
selected_target_prob = float(target_prob_by_token.get(proposed_token_id, 0.0) or 0.0)
selected_draft_prob = float(draft_prob_by_token.get(proposed_token_id, 0.0) or 0.0)
if selected_draft_prob > 0.0:
    pq_acceptance_prob = min(1.0, selected_target_prob / selected_draft_prob)
    pq_draw = deterministic_probability_draw(...)
    pq_accepted = pq_draw <= pq_acceptance_prob
```

```python
if pq_accepted:
    accepted_step_token_ids.append(proposed_token_id)
else:
    correction_token_ids = [target_best_token_id][:max_correction_tokens]
    break
```

Why this is core:

- This is the first node where `llama_true_tree_pq_tokens` stops sharing the legacy piece-prefix acceptance behavior and starts running a distinct per-token acceptance loop on real token ids.
- It also adds the "all accepted then append one target follow-up token" behavior that makes the experimental real-token lane much closer to the standard speculative decoding control flow than the older mixed-space tree verifier.

## Reviewed But Not Listed As Feature Nodes

These commits were reviewed during the git pass but were not promoted to the main feature list because they were documentation-only, ignore-only, template-only, or cleanup-only:

- `5c33fa5`
- `c032d4f`
- `b094c79`
- `ed8737f`
- `2607fdb`
- `4164ee6`
- `160f200`
- `5bca403`
- `a44a25e`
- `4528aa0`
- `832df76`
- `f2fcfb7`
- all later `docs:`-only commits

They still matter historically, but they did not complete a new standalone runtime feature by themselves.
