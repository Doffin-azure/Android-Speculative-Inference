# llama.cpp Integration Plan

更新时间: 2026-03-30

## Collaboration Rules - 2026-03-30

- Add and maintain a proper `.gitignore` for Android Studio, Gradle, native build outputs, and local machine files.
- After each completed work session, sync the git repository before moving on to the next stage.
- Codex is responsible for the git sync workflow unless the user says otherwise.
- All Gradle sync, build, CMake configure/build, app run, and device verification steps are done in Android Studio by the user.
- Codex should not run project build commands unless the user explicitly changes this rule later.
- When build-related changes are made, record what needs to be verified in Android Studio instead of running terminal builds.

## Continuation Update - 2026-03-30

Completed in this session:
- `:lib` now contains a JNI landing zone instead of only pure-Kotlin stub code.
- Added `lib/src/main/cpp/CMakeLists.txt`
- Added `lib/src/main/cpp/ai_chat.cpp`
- Added `NativeBridge.kt` and `NativeInferenceEngine.kt`
- `AiChat` now prefers the native-backed engine and falls back to the stub engine if JNI loading fails.
- `InferenceEngine` now exposes backend/status inspection methods needed by the app layer.
- `LocalLlmImpl` now reads backend/model/error state from `:lib` instead of maintaining duplicate cache state.
- `lib/build.gradle.kts` now declares its own `externalNativeBuild` + `arm64-v8a` setup.
- `gradle.properties` now uses `kotlin.compiler.execution.strategy=in-process` to avoid local Kotlin daemon permission issues in this environment.

Validation completed in previous session:
- `:lib:assembleDebug` passed.
- `:app:assembleDebug` passed.
- Both `app` and `lib` CMake steps completed for `arm64-v8a`.

From 2026-03-30 onward, repeat verification in Android Studio instead of terminal builds.

Current effective call chain:

`MainViewModel(AndroidViewModel) -> LocalLlmImpl(context) -> AiChat.getInferenceEngine(context) -> :lib/InferenceEngineImpl -> lib/src/main/cpp/ai_chat.cpp`

Remaining next step:
- Replace `lib/src/main/cpp/ai_chat.cpp` and `lib/src/main/cpp/CMakeLists.txt` with the real `llama.cpp/examples/llama.android/lib` integration structure.

## API Alignment Update - 2026-03-30

Based on the current official `llama.cpp` Android sample:
- `docs/android.md` still points to importing `examples/llama.android` into Android Studio.
- `AiChat.kt` now exposes `getInferenceEngine(context)`.
- `InferenceEngine.kt` now uses `sendUserPrompt(...)`, `setSystemPrompt(...)`, `bench(...)`, `cleanUp()`, and `destroy()`.

Local alignment completed:
- Added a context overload to local `AiChat`.
- Expanded local `InferenceEngine` state and lifecycle surface to better match the official sample while keeping compatibility with current app code.
- Renamed the native landing-zone source file from `ai_chat_stub.cpp` to `ai_chat.cpp` so the file layout is closer to the official sample.

Android Studio verification needed by user:
- Sync Gradle project.
- Confirm `:lib` still indexes correctly after the `InferenceEngine` API expansion.
- Confirm native source rename from `ai_chat_stub.cpp` to `ai_chat.cpp` is reflected in the Android Studio CMake model.

## Source Switch Prep - 2026-03-30

Local preparation completed:
- `:lib` now accepts an optional Gradle property `llamaCppSourceDir`.
- `:lib` also accepts the environment variable `LLAMA_CPP_SRC` as a fallback.
- `lib/src/main/cpp/CMakeLists.txt` now detects whether `LLAMA_CPP_SRC` points to a valid `llama.cpp` checkout.
- If no source path is provided, CMake stays on the current stub path.
- This keeps the project safe to open now while preparing for a later real-source migration.

Android Studio verification needed by user:
- Sync Gradle project after the new optional `llamaCppSourceDir` handling.
- If you later clone `llama.cpp`, provide the path from Android Studio Gradle settings or a local Gradle property and confirm CMake sees it.

Recommended future path injection order:
1. Put `llamaCppSourceDir=...` into a user-local Gradle property that is not committed.
2. If that is inconvenient, use environment variable `LLAMA_CPP_SRC`.
3. Do not hardcode a machine-specific llama.cpp path into tracked project files.

## Path Config Convenience - 2026-03-30

Completed in this node:
- Added environment-variable fallback for the future llama.cpp source path in `lib/build.gradle.kts`.
- Documented the preferred order for local-only path configuration.

Android Studio verification needed by user:
- Sync Gradle project and confirm no issues from the added environment-variable fallback.
- When you are ready to start real integration later, configure the path locally without modifying tracked files.

## Local Config Template - 2026-03-30

Completed in this node:
- Added `gradle-local.template.properties` as a checked-in example for future machine-local llama.cpp path settings.
- Added `gradle-local.properties` to `.gitignore` so the real local file can stay untracked.

How this will be used later:
- Copy `gradle-local.template.properties` to `gradle-local.properties`.
- Put `llamaCppSourceDir=...` into that local-only file when it is time to start real llama.cpp integration.
- Keep tracked project files machine-agnostic.

Android Studio verification needed by user:
- No build change expected.
- Optionally confirm the template file is visible in the project and the ignored `gradle-local.properties` convention is acceptable.

## Local Property Loading - 2026-03-30

Completed in this node:
- Updated `lib/build.gradle.kts` so it really reads `gradle-local.properties` from the project root.
- The future llama source path is now resolved in this order:
  `-PllamaCppSourceDir` -> `gradle-local.properties` -> `LLAMA_CPP_SRC`.

Why this matters:
- The local template added earlier is now backed by real loading behavior.
- Future llama.cpp path setup can stay entirely local without editing tracked files.

Android Studio verification needed by user:
- Sync Gradle project.
- Optionally create a local `gradle-local.properties` later and confirm the property is picked up when needed.

## Build Script Fix - 2026-03-30

Completed in this node:
- Fixed `lib/build.gradle.kts` after Android Studio reported Kotlin DSL script compilation errors.
- Replaced the fragile `java.util.Properties()` / `use(::load)` form with explicit `import java.util.Properties` and `use { input -> load(input) }`.

Why this mattered:
- The previous script form was accepted in theory but failed in the Gradle Kotlin DSL script compilation context used by Android Studio.
- This was a real integration blocker, so it was corrected immediately and recorded here.

Android Studio verification needed by user:
- Re-run Gradle Sync / build model load.
- Confirm the `:lib` script now configures without Kotlin DSL compilation errors.

## Archive Consistency Fix - 2026-03-30

Completed in this node:
- Updated outdated call-chain text in the archive so it matches the current app wiring.
- Removed stale references that still implied the old `StubLlamaEngine` main path.

Why this matters:
- The archive is now safe to use as the single source of truth when resuming work.

## Config Ergonomics Polish - 2026-03-30

Completed in this node:
- Added explicit path-resolution instructions to `gradle-local.template.properties`.
- Added comments in `lib/build.gradle.kts` and `lib/src/main/cpp/CMakeLists.txt` to clarify that machine-local llama.cpp paths must not be committed.
- Clarified the exact handoff point between the current stub path and the future real-source integration.

Why this matters:
- The remaining setup is now discoverable directly from the files the next integration step will touch.
- This reduces the chance of path confusion when real llama.cpp work begins.

## Preparation Complete - 2026-03-30

Status:
- All preparation-only nodes are complete.
- There are no remaining housekeeping, wiring, local-config, or archive-consistency tasks that should be done before real integration starts.

Next phase boundary:
- The next meaningful step is the real migration of official `llama.cpp/examples/llama.android/lib` build/native structure into this project.
- Starting from that point, the work is no longer preparation; it is actual llama.cpp integration.

## Actual Integration Start - 2026-03-30

Completed in this node:
- Replaced the ad-hoc `NativeInferenceEngine` bridge with an official-style `InferenceEngineImpl` singleton in `:lib`.
- Changed `AiChat` to prefer `InferenceEngineImpl.getInstance(context)` and only fall back to `StubInferenceEngine` if native loading fails.
- Migrated `ai_chat.cpp` to an official-style engine JNI contract:
  `init`, `load`, `prepare`, `systemInfo`, `benchModel`, `processSystemPrompt`, `processUserPrompt`, `generateNextToken`, `unload`, `shutdown`.
- Switched the `:lib` native library naming and CMake project shape closer to the official sample by moving to `ai-chat`.
- Updated `lib/src/main/cpp/CMakeLists.txt` so that, when `LLAMA_CPP_SRC` is supplied, it begins using official-style `add_subdirectory(...)`, include paths, and `llama/common/android` linking.

Current status:
- Kotlin and C++ entry points are now shaped for real llama.android integration.
- Native behavior is still stubbed until the actual llama.cpp source tree is supplied and the real native body is migrated.

Android Studio verification needed by user:
- Sync Gradle project.
- Confirm `:lib` resolves after the `InferenceEngineImpl` migration.
- Confirm the new native library name `ai-chat` is reflected without unresolved symbol errors.

## Integration Consistency Pass - 2026-03-30

Completed in this node:
- Updated the archive’s top-level call chain so it matches the new `InferenceEngineImpl` architecture.
- Relaxed `InferenceEngineImpl` cleanup handling so transitional initialization state is tolerated more safely.

Why this matters:
- The archive once again matches the actual code path after the first migration wave.
- Early lifecycle calls are less likely to trip over the engine’s initialization boundary.

## App JNI Removal - 2026-03-30

Completed in this node:
- Removed the obsolete app-local JNI bridge `LlamaBridge.kt`.
- Removed `app/src/main/cpp/CMakeLists.txt` and `app/src/main/cpp/llama_jni.cpp`.
- Removed `app` module `externalNativeBuild` wiring so the application no longer builds an unused native target.
- Removed the now-empty `app/src/main/cpp` directory from the project tree.

Current structure:
- `app` is now fully a UI/application shell.
- `:lib` is now the only native integration module.

Android Studio verification needed by user:
- Sync Gradle project.
- Confirm `app` no longer expects its own CMake/native configuration.
- Confirm native build responsibility is now entirely under `:lib`.

## Official Native Replacement - 2026-03-30

Completed in this node:
- Replaced `lib/src/main/cpp/ai_chat.cpp` with an official `llama.cpp/examples/llama.android/lib`-derived implementation adapted to the local package name.
- Added `lib/src/main/cpp/logging.h` from the official Android sample.
- Updated `lib/build.gradle.kts` with the key official CMake arguments needed for real `llama.cpp` builds.
- Created a machine-local `gradle-local.properties` pointing at the cloned local checkout:
  `C:\Users\JXZ\AndroidStudioProjects\llama.cpp`

Current status:
- The project is no longer using a hand-written stub native shell.
- The native layer is now shaped around the official llama.android implementation and is ready to compile against the local llama.cpp checkout.

Android Studio verification needed by user:
- Re-sync Gradle so `gradle-local.properties` is picked up.
- Confirm `:lib` CMake now resolves headers and targets from the local `llama.cpp` checkout.
- Confirm whether the next failure, if any, is now a real upstream integration/build issue rather than a local project-structure issue.

## Official Build Parity Pass - 2026-03-30

Completed in this node:
- Brought `lib/src/main/cpp/CMakeLists.txt` closer to the official Android sample by adding ABI-based `GGML_SYSTEM_ARCH`, `GGML_CPU_KLEIDIAI`, and `GGML_OPENMP` handling.
- Added the related compile definitions for the `ai-chat` target when building against a real `llama.cpp` checkout.
- Added `-DCMAKE_BUILD_TYPE=Release` to `lib/build.gradle.kts` so the native configuration is closer to the official sample defaults.

Why this matters:
- The project’s CMake behavior is now much closer to the official `examples/llama.android/lib` layout.
- Any remaining failures are increasingly likely to be genuine upstream integration issues instead of missing local build flags.

## Interface Noise Cleanup - 2026-03-30

Completed in this node:
- Removed the unused stub-era `draftTokenIds` method from the app-local `LocalLlm` adapter.
- Added an explicit historical-note override so any older references to app-local JNI centrality are not mistaken for the current design.

Why this mattered:
- `draftTokenIds` was no longer part of the real migration direction.
- Removing it reduces one more source of confusion before actual llama.cpp integration starts.

## ViewModel Cleanup Wiring - 2026-03-30

Completed in this node:
- Connected `MainViewModel.onCleared()` to `LocalLlm.cleanup()`.
- Prepared the app lifecycle for future native/resource cleanup once the real llama.cpp engine is attached.

Why this matters:
- The current stub does not strongly need cleanup, but the real engine almost certainly will.
- This reduces lifecycle-related refactor work later.

Android Studio verification needed by user:
- Sync/build model check only.
- Confirm there are no IDE issues after overriding `onCleared()` in `MainViewModel`.

## Context Wiring Alignment - 2026-03-30

Completed in this node:
- Switched the active app inference path to request the engine through `AiChat.getInferenceEngine(context)`.
- Updated `LocalLlmImpl` to require an Android `Context`.
- Updated `MainViewModel` to `AndroidViewModel` so the app can provide `Application` context without inventing a custom factory yet.

Why this matters:
- The official `llama.android` sample exposes the engine through a context-aware entry point.
- This removes one more mismatch before real llama.cpp integration begins.

Android Studio verification needed by user:
- Sync Gradle project and confirm `MainViewModel` still instantiates correctly through `by viewModels()`.
- Confirm there are no IDE errors after changing `MainViewModel` from `ViewModel` to `AndroidViewModel`.

## App Adapter Alignment - 2026-03-30

Completed in this node:
- Expanded the app-layer `LocalLlm` abstraction so it is closer to the richer `:lib` inference API.
- Added app-layer placeholders for `setSystemPrompt(...)`, `benchmark(...)`, and `cleanup()`.
- Wired `LocalLlmImpl` to forward those calls into `:lib`.

Why this matters:
- The app layer is no longer shaped only around the earliest stub use case.
- Future UI work can consume richer llama features without redesigning the adapter boundary first.

Android Studio verification needed by user:
- Sync Gradle project and confirm the new `LocalLlm` methods do not introduce IDE errors.
- No UI changes are expected yet; this is API-surface preparation only.

## Legacy Bridge Clarification - 2026-03-30

Completed in this node:
- Marked the `app` module JNI bridge as legacy/reference-only.
- Added comments in `app/build.gradle.kts`, `app/src/main/java/.../LlamaBridge.kt`, and `app/src/main/cpp/*` to reduce confusion about the active migration path.
- Confirmed the intended real integration target remains `:lib`, not the old app-local JNI files.

Current rule of thumb:
- Keep `app/src/main/cpp/llama_jni.cpp` buildable for now.
- Do not extend the old `app` JNI path with new llama.cpp logic.
- Put all new local inference integration work into `:lib`.

Android Studio verification needed by user:
- Sync Gradle project and ensure the new comments/metadata changes do not affect indexing.
- Continue treating `:lib` as the only module where future llama.cpp integration work should land.

## 当前状态

项目已经具备这些基础：

- Compose UI / `ViewModel` 状态流可运行
- Kotlin `LocalLlm` 抽象已建立
- JNI 桥 `LlamaBridge` 已打通
- native 侧当前是 `stub-jni`，会校验模型文件路径是否存在
- stub 桥接已补充显式状态接口：
  - `isModelLoaded()`
  - `loadedModelPath()`
  - `lastError()`
- UI / `ViewModel` 已补充这些接真实后端前需要的基础状态：
  - 模型加载中 / 推理中禁用按钮
  - 当前状态文本
  - 最近错误信息
  - 已加载模型路径展示

当前还没有接入真实 `llama.cpp`，所以：

- `Load Model` 只验证路径存在
- `Run Local` 只返回 stub 文本

## 下一步目标

把官方 `llama.cpp/examples/llama.android` 跑通，然后迁移成熟实现到本项目。

## 已核对的官方示例结构

基于官方仓库 `ggml-org/llama.cpp` 当前 `master` 分支的 `examples/llama.android`：

- 工程不是单模块，而是 `:app + :lib`
- 真正的 `llama.cpp` 集成主要在 `lib` 模块
- `app` 模块主要负责界面与调用 `lib`
- `lib` 模块包含：
  - Kotlin API：`AiChat.kt`、`InferenceEngine.kt`
  - native 代码：`lib/src/main/cpp/ai_chat.cpp`
  - native 构建：`lib/src/main/cpp/CMakeLists.txt`

### 官方示例的关键设计

- Kotlin 对外入口不是直接暴露若干 JNI 函数，而是通过 `InferenceEngine` 抽象能力
- `InferenceEngine` 持有 `StateFlow<State>`，状态包括：
  - `LoadingModel`
  - `ModelReady`
  - `Generating`
  - `Error`
- 用户 prompt 输出不是一次性 `String`，而是 `Flow<String>` 流式返回 token/文本片段
- native CMake 不是单文件 stub 编译，而是：
  - `add_subdirectory(${LLAMA_SRC} build-llama)`
  - 直接把 `llama.cpp` 源码作为子目录编进来
  - 链接 `llama`、`common`、`android`、`log`

### 与当前项目的差异

当前项目：

- 单模块 `app`
- JNI 入口集中在 `app/src/main/cpp/llama_jni.cpp`
- Kotlin 接口仍是 stub 风格：
  - `loadModel(): Boolean`
  - `generate(): String`
  - `draftTokenIds(): IntArray`

官方示例：

- 推荐把真实推理能力放到单独 `lib` 模块
- 推荐用状态机 + 流式输出，而不是单次同步字符串返回
- CMake 直接纳入 `llama.cpp` 根源码，而不是只编译一个 JNI 壳文件

## 当前迁移判断

为了降低风险，下一步不要直接把官方 `ai_chat.cpp` 硬塞进当前 `app/src/main/cpp`。

更稳妥的迁移顺序是：

1. 保留当前 `app` 的 Compose/UI/ViewModel 骨架
2. 在本项目中新增一个独立 `llama` 或 `llama-lib` 模块
3. 参考官方 `examples/llama.android/lib`：
   - 迁入 Kotlin `InferenceEngine` 风格抽象
   - 迁入 `CMakeLists.txt` 组织方式
   - 迁入 `ai_chat.cpp` 风格的 native 桥接
4. 再让当前 `LocalLlmImpl` 改为调用新模块，而不是继续直接绑死在 stub JNI 上

## 已完成的本地骨架准备

为了给官方结构留出承接层，当前项目已经新增：

- Gradle 模块：`:lib`
- 目录：`lib/`
- 占位接口：`lib/src/main/java/com/example/myapplication/llama/LlamaEngine.kt`

当前这个 `lib` 模块还只是“迁移 landing zone”：

- 先对齐官方 `InferenceEngine` 的接口形态
- 先提供 `StateFlow` + `Flow<String>` 这种更接近真实推理的抽象
- 还没有接入真实 `llama.cpp`
- `app` 已开始依赖 `:lib`
- `LocalLlmImpl` 已切到 `StubLlamaEngine`
- 现有 `app/src/main/cpp/llama_jni.cpp` 仍保留，但不再是主调用路径

## 当前阻塞点

- 终端默认没有配置 `JAVA_HOME`，直接运行 `gradlew` 会失败。
- 使用 Android Studio 自带 JBR 可启动 Gradle：
  - `C:\Program Files\Android\Android Studio\jbr`
- 默认 `C:\Users\JXZ\.gradle` 下的 wrapper 锁文件存在权限问题，已改为项目内 `GRADLE_USER_HOME=.gradle-user` 规避。
- 上一次 `assembleDebug` 在项目内 Gradle home 下运行时被手动中断，因此还没有拿到完整构建结果。
- 继续探测时应遵守：
  - 单次命令超过 60 秒就停止
  - 停止后优先汇报卡在依赖下载、Gradle 配置、NDK/CMake、还是源码编译阶段
- 当前补充确认：
  - Android Studio 内 `assembleDebug` 已成功
  - `configureCMakeDebug[arm64-v8a]` 与 `buildCMakeDebug[arm64-v8a]` 均可通过
  - 当前项目自己的 stub JNI/CMake 链路是健康的

## 建议落地顺序

1. 下载 `llama.cpp` 仓库到本机。
2. 优先在 Android Studio 中单独打开并运行 `examples/llama.android`。
3. 确认官方 demo 在真机上可以完成模型加载和推理。
4. 对照官方 demo，梳理这几部分：
   - Kotlin 封装入口
   - JNI 符号与 native 桥接
   - `CMakeLists.txt` 与 `libllama` 依赖组织
   - 模型文件放置和访问方式
5. 再把本项目的 stub 实现替换为真实实现。

## 现在最合适的下一步

下一步优先做其中一件：

1. 下载完整 `llama.cpp` 仓库到本机，并在 Android Studio 单独打开 `examples/llama.android`
2. 如果暂时不单独打开官方示例，则先在本项目内新建 `lib` 模块骨架，按官方结构为后续迁移腾位置

更推荐第 1 种，因为这样可以先确认官方示例在你的机器和手机上直接可运行。

## 当前主调用链

当前本项目的本地推理调用链已经变为：

`MainViewModel(AndroidViewModel) -> LocalLlmImpl(context) -> AiChat.getInferenceEngine(context) -> :lib/NativeInferenceEngine`

这意味着下一步接真实实现时，优先替换：

- `lib/src/main/java/com/example/myapplication/llama/LlamaEngine.kt`
- 后续新增的 `lib/src/main/cpp/*`
- `lib/build.gradle.kts`

而不是先改 UI 或 ViewModel。

## 恢复工作时的建议命令

如果在终端里继续排查构建，优先带上这些环境变量：

```powershell
$env:JAVA_HOME='C:\Program Files\Android\Android Studio\jbr'
$env:PATH="$env:JAVA_HOME\bin;$env:PATH"
$env:GRADLE_USER_HOME='c:\Users\JXZ\AndroidStudioProjects\MyApplication2\.gradle-user'
```

## 建议替换点

本项目中优先替换这些文件：

- `app/src/main/cpp/llama_jni.cpp`
- `app/src/main/cpp/CMakeLists.txt`
- `app/src/main/java/com/example/myapplication/inference/LlamaBridge.kt`
- `app/src/main/java/com/example/myapplication/inference/LocalLlmImpl.kt`

UI 和 `ViewModel` 层原则上可以继续复用，只需要在真实能力接入后调整：

- 模型加载耗时提示
- 推理中禁用按钮
- 错误信息展示
- 模型文件选择器

## 导入前的注意点

- `System.loadLibrary("llama-jni")` 与 CMake 目标名必须保持一致。
- JNI 符号中的包名必须继续匹配 `com.example.myapplication.inference.LlamaBridge`。
- 当前 Gradle 已限制 `abiFilters` 为 `arm64-v8a`，适合作为第一阶段真机构建目标。
- 如果官方示例里的 `libllama` API 与当前认知不同，以官方示例为准，不要强行保留 stub 时代的接口细节。

## 本项目当前 stub 的意义

这套 stub 不是最终方案，它的作用是：

- 让 Kotlin -> JNI -> C++ -> Kotlin 这条链始终可编译、可观察
- 在真实 `llama.cpp` 接入前，先稳定上层 UI 和状态流
- 为后续替换保留固定入口
