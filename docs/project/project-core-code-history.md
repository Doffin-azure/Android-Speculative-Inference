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
