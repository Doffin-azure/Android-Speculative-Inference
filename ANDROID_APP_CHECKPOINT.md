# Android App Checkpoint

## Long-Term Roadmap - 2026-03-30

This project is ultimately aimed at phone + computer cooperative speculative decoding, not only phone-local inference.

Planned stage order:
1. Stabilize local Android runtime with real `llama.cpp`.
2. Validate real model load and minimal prompt generation on device.
3. Add a computer-side inference service.
4. Add a normal phone-to-computer inference path first.
5. Build speculative decoding with phone-local draft generation and computer-side target verification.
6. Tune performance, robustness, and user experience after the full loop works.

Current stage:
- build integration is done
- runtime validation is the active next step
- speculative decoding remains the long-term destination, not the immediate next code task

更新时间: 2026-03-29

## Collaboration Rules - 2026-03-30

- Repository hygiene: keep Android Studio, Gradle, native build output, and local environment files out of git via `.gitignore`.
- Workflow rule: after each completed task/session, sync the git repository.
- Workflow clarification: when a task/session is completed, record a short human-readable git sync summary describing what changed before or alongside the sync.
- Build rule: all Gradle sync, compile, CMake, install, and runtime verification steps are performed in Android Studio by the user.
- Codex should focus on code/document edits and should not run project build commands unless this rule is explicitly changed later.
- Bundle rule: Android bundle / packaging / bundle verification is performed by the user; Codex should not run bundle-related steps and should instead tell the user exactly what to verify.

## Collaboration Update - 2026-03-30

Effective from this checkpoint:
- Do not forget git sync after each completed node.
- Do not treat git sync as silent housekeeping; include an explicit explanation of what the node changed.
- Do not stop at the git explanation; also record the node summary in the markdown checkpoint/archive documents.
- Do not let Codex perform bundle work.
- If a bundle or packaging step is needed, ask the user to do it in Android Studio and provide the expected verification points.

## Preparation Complete - 2026-03-30

The pre-integration preparation phase is now complete.

Current ready state:
- `:lib` is the only intended landing zone for real `llama.cpp` integration.
- The app now reaches the engine through `AiChat.getInferenceEngine(context)`.
- The app adapter surface already includes room for richer engine features such as system prompts, benchmarking, and cleanup.
- Lifecycle cleanup wiring is already in place in `MainViewModel`.
- Machine-local llama.cpp source configuration is prepared through:
  `-PllamaCppSourceDir`, `gradle-local.properties`, or `LLAMA_CPP_SRC`.
- Local config templates and ignore rules are in place, so machine-specific paths do not need to touch tracked files.

What this means:
- There are no more preparation-only nodes that need to be completed before starting the real integration.
- The next step is no longer project preparation; it is the actual migration of official `llama.cpp/examples/llama.android/lib` native and Gradle/CMake structure into this project.

## Historical Note - 2026-03-30

Some older sections below still describe the first stub-era layout where `app/src/main/cpp`, `LlamaBridge`, or `draftTokenIds` looked more central.

Treat those as historical notes only.
The current source of truth is:
- real integration target: `:lib`
- active engine path: `MainViewModel -> LocalLlmImpl -> AiChat.getInferenceEngine(context) -> :lib`
- old app-local JNI path: retained only as legacy/reference code

## App JNI Removed - 2026-03-30

The old app-local JNI bridge has now been removed from the active project structure.

Current structure:
- `app` no longer owns `externalNativeBuild`
- `app/src/main/cpp` is no longer part of the active integration path
- all native integration responsibility is now concentrated in `:lib`

Any older notes below that discuss `app/src/main/cpp` or `LlamaBridge` should be treated as historical background only.

## First Real Native Build Success - 2026-03-30

Android Studio has now completed a successful native build with the local `llama.cpp` checkout wired in.

Current project status:
- real `llama.cpp` sources are participating in the Android build
- `:lib` is the active native integration module
- the remaining work is runtime validation, on-device behavior checks, and fixing any model-load / inference issues that appear next

## Handoff Summary - 2026-03-30

If work is resumed in a new context, the short version is:
- build integration is already successful
- next step is device runtime validation, not more project scaffolding
- test order should be:
  1. run app
  2. load real model
  3. run minimal prompt
  4. inspect UI status + Logcat if anything fails

## Model Directory Picker Update - 2026-03-30

Completed in this node:
- Replaced the "manual model path only" flow with a system directory picker entry point.
- After a directory is selected, the app now scans for readable `.gguf` files.
- If exactly one model is found, it is selected automatically.
- If multiple models are found, the UI now lists them explicitly so the user can choose which file to load.

What this means:
- Model selection is now better aligned with real device usage.
- Runtime validation can focus more on model load/inference behavior and less on manual path entry mistakes.

## Runtime Correctness Fixes - 2026-03-30

Completed in this node:
- Fixed the engine initialization wait path so model loading no longer fails early just because native initialization is still finishing in the background.
- Fixed app-side generation collection so streamed output chunks are concatenated into the full response instead of only keeping the first emitted segment.

Why this matters:
- These were runtime-behavior bugs, not UI polish.
- They directly affect whether on-device validation reflects real model behavior.

## Runtime Error Surfacing Fix - 2026-03-30

Completed in this node:
- Improved initialization failure reporting so load attempts now surface the underlying engine error instead of collapsing everything into a generic `engine is not ready yet` message.

Why this matters:
- The next runtime test should give a more actionable failure message if native init/backends/library loading is the real problem.

## SAF Import Fix - 2026-03-30

Completed in this node:
- Stopped relying on direct external-storage file readability after SAF directory selection.
- The app now prepares a readable app-local copy of the selected `.gguf` file before passing its path into the native engine.

Why this matters:
- This directly targets the observed `Cannot read file` failure on device.
- It avoids fragile assumptions about converting SAF-selected content into directly readable filesystem paths.

## Native Load Diagnostics Upgrade - 2026-03-30

Completed in this node:
- Added native preflight checks before `llama_model_load_from_file()` runs.
- Load failures now distinguish between file-open failure, empty file, suspiciously small file, and invalid/non-GGUF header cases.

Why this matters:
- The next on-device failure should be much more informative than a generic `Failed to load model: 1`.

## Desktop GGUF Check Environment - 2026-03-30

Completed in this node:
- Added a reusable local script `tools/gguf_check.py` for reading GGUF metadata on the computer.
- Created a project-local virtual environment `.venv-gguf` and verified it can read the imported model through `llama.cpp/gguf-py`.

Validated on:
- `Llama-3.2-1B-Instruct-Q4_K_M.gguf`
- header: `GGUF`
- version: `3`
- size: about `770 MB`

Why this matters:
- The computer can now be used to quickly distinguish "bad model file" from "Android-side loading/runtime issue".

## Documentation Library Update - 2026-03-30

Completed in this node:
- Added a curated `docs/` library for operational knowledge.
- Added a desktop runtime supplement, current-status summary, workflow rules summary, and root-document map.

Primary entry point:
- `docs/README.md`

Why this matters:
- New work can resume from the curated docs first instead of searching through long root-level archives.

## Desktop Runtime Success - 2026-03-30

Completed in this node:
- Confirmed that the computer-side WSL `llama-cli` environment can load `Llama-3.2-1B-Instruct-Q4_K_M.gguf`.
- Confirmed that the same file can produce a normal text response from a minimal `Hello` prompt.

Why this matters:
- The model file is no longer only "structurally valid"; it is now proven runnable on the computer.
- The Android-side failure should now be treated primarily as an Android runtime/integration issue rather than a bad-model suspicion.

## Android Diagnostics UI And Logging - 2026-03-30

Completed in these recent nodes:
- Added copyable read-only UI fields for `Last Error`, `Output`, `Event Log`, and the diagnostic log path.
- Added event-log accumulation in the app layer so runtime steps are easier to reconstruct.
- Added automatic writing of the latest diagnostic snapshot into the app-private file:
  `files/logs/diagnostic-latest.txt`
- Added a fix for the Compose diagnostics-header layout compile error after the first UI iteration.

Why this matters:
- Android-side failures can now be copied directly from the UI.
- Android Studio `Device File Explorer` can now pull a stable diagnostic text file instead of relying only on screenshots or manual copying.

## Android Backend Root-Cause Narrowing - 2026-03-30

Completed in these recent nodes:
- Added fallback loading with `use_mmap = false` after initial native load failure.
- Added propagation of recent native load diagnostics into the UI error text.
- Confirmed from device diagnostics that the previous failure reason was:
  `no backends are loaded`
- Switched Android build/runtime configuration away from dynamic ggml backend loading and toward built-in backend loading for a more stable baseline.

Why this matters:
- The runtime failure has been narrowed from a vague Android incompatibility suspicion to a specific backend-loading problem.
- Current Android verification should now test whether the built-in backend path restores successful model loading.

## Android Local Baseline Success - 2026-03-30

Completed in this node:
- Confirmed that the Android app can now load `Llama-3.2-1B-Instruct-Q4_K_M.gguf` on device.
- Confirmed that the imported model copy is used successfully from:
  `/data/user/0/com.example.myapplication/files/imported-models/Llama-3.2-1B-Instruct-Q4_K_M.gguf`
- Confirmed that a minimal prompt completes local generation successfully on device.
- Verified that the built-in ggml backend path resolved the previous `no backends are loaded` failure.

Observed result summary:
- `Model loaded: true`
- `Status: Inference complete.`
- minimal prompt output returned visible text

Why this matters:
- The project has now crossed the key local-baseline milestone:
  Android can load a real GGUF model and generate text locally.
- The immediate next work should move above this baseline instead of reopening earlier backend-load uncertainty.

## Ignore Rules Update - 2026-03-30

Completed in this node:
- Updated `.gitignore` to exclude local GGUF model files.
- Updated `.gitignore` to exclude the local `MIDTERM_REPORT.md` file from repository sync.

Why this matters:
- Large local model artifacts and local reporting drafts will no longer keep appearing as untracked noise.
- Repository sync can stay focused on code and project documentation that should actually be versioned.

## 当前目标

开发一个 Android 手机上的本地推理 App，后续再扩展到：

- 本地 GPU / NPU 推理
- 云端推理
- 手机本地 draft + 云端 target 的投机解码

当前阶段只做到：

- Android 开发环境打通
- 真机部署成功
- Kotlin/Compose 项目骨架建立
- `ViewModel` 状态管理建立
- JNI 骨架打通

还没有开始：

- 真实 `llama.cpp` 集成
- 模型文件选择与加载
- 云端 WebSocket
- speculative decoding 协议

## 已确认的开发路线

优先路线：

- Windows 上做 Android 原生开发
- VS Code 可作为主要编辑器
- Android Studio 负责 SDK / NDK / 模拟器 / 首次项目创建 / 必要同步
- WSL 更适合后续跑 Python/FastAPI 云端服务，不适合作为 Android 主开发环境

原因：

- 真机调试、ADB、NDK、Gradle、Android Studio 在 Windows 原生更顺
- 手机上的 GPU / NPU / 发热 / 内存测试必须在真机上做

## 环境部分已完成

已完成的认知和配置：

- 用户有电脑和一台手机
- Android 开发优先选真机，不选模拟器
- 手机 USB 连接时优先选“文件传输”，不要选 MIDI
- 已打开 USB 调试
- Android Studio 已能正常连接手机并运行默认 App

已讨论和确认的组件安装方式：

在 Android Studio 的 `SDK Manager` 中安装：

- `Android SDK`
- `Android SDK Platform-Tools`
- `Android SDK Build-Tools`
- `Android SDK Command-line Tools (latest)`
- `NDK (Side by side)`
- `CMake`

## 项目创建部分已完成

已完成：

- 使用 Android Studio 创建了 Android 项目
- 项目名为 `My Application`
- 已成功运行到真机

提醒：

- `Android` 视图会折叠真实目录，只显示 `manifests`、`kotlin+java`、`res`
- 需要看真实路径时，要切到 `Project` 视图

## 项目结构设计

在 `kotlin+java` 对应的包名下，已经规划了这些 package：

- `ui`
- `inference`
- `network`
- `viewmodel`

后续 native 目录应位于：

- `app/src/main/cpp`

## 已建立的代码架构

### UI 层

- `MainScreen.kt`

职责：

- 显示模型状态
- 输入模型路径
- 输入 prompt
- 触发加载模型
- 触发本地推理
- 展示输出

### 推理接口层

- `LocalLlm.kt`
- `LocalLlmImpl.kt`
- `LlamaBridge.kt`

职责：

- 抽象本地模型能力
- 通过 JNI 调用 native 层

### 状态管理层

- `MainViewModel.kt`

职责：

- 管理 `output`
- 管理 `isModelLoaded`
- 管理 `modelPath`
- 统一处理 `loadModel()` 和 `runLocal()`

### Activity 层

- `MainActivity.kt`

职责：

- 绑定 `ViewModel`
- 将状态传给 `MainScreen`

## 目前功能状态

当前 App 应具备：

- 显示 `Model: Loaded / Not loaded`
- 输入 `Model Path`
- 点击 `Load Model`
- 输入 `Prompt`
- 点击 `Run Local`
- 显示输出

当前 native 仍为假实现，但整条链已经打通：

- Kotlin -> JNI -> C++ -> Kotlin UI

运行成功后的行为应类似：

- 点击 `Load Model` 返回成功
- 输入 prompt 后点击 `Run Local`
- 输出形如 `JNI output: <你的输入>`

## 已踩过的关键问题

### 1. `MainActivity` 重复声明

出现过：

- `Redeclaration: class MainActivity : ComponentActivity`

原因：

- 项目中存在重复的 `MainActivity`
- 或同一个文件残留了默认模板和新代码两份定义

处理方式：

- 全局搜索 `class MainActivity`
- 保证只保留一个定义

### 2. 找不到 `cpp` 目录

原因：

- 当时处于 `Android` 视图
- 该视图不会直接暴露真实目录结构

处理方式：

- 切换到 `Project` 视图
- 在 `app/src/main/` 下手动创建 `cpp` 目录

### 3. 找不到 `app/build.gradle.kts`

原因：

- 混淆了 `app/build/` 目录和 `app/build.gradle.kts` 文件

处理方式：

- 搜索并打开 `app/build.gradle.kts`
- 不要误改 `app/build/` 生成目录

## 当前 native / JNI 状态

已设计的 JNI 桥：

- `LlamaBridge.kt`
  - `loadModel(modelPath: String): Boolean`
  - `generate(prompt: String, maxTokens: Int): String`
  - `draftTokenIds(prompt: String, count: Int): IntArray`

native 侧已规划文件：

- `app/src/main/cpp/llama_jni.cpp`
- `app/src/main/cpp/CMakeLists.txt`

`System.loadLibrary("llama-jni")` 与 CMake 中的库名必须一致。

JNI 方法名必须和包名完全匹配。如果包名不是：

- `com.example.myapplication`

则 `llama_jni.cpp` 中的 JNI 符号名也必须同步修改。

## `app/build.gradle.kts` 当前认知

已确认项目使用 `build.gradle.kts`。

用户贴出的模块级 Gradle 文件已经包含：

- `externalNativeBuild`
- `cmake.path = file("src/main/cpp/CMakeLists.txt")`
- `cmake.version = "3.22.1"`

还补充建议过：

```kotlin
ndk {
    abiFilters += listOf("arm64-v8a")
}
```

目的：

- 先只构建手机常用的 `arm64-v8a`
- 降低 native 构建复杂度

## 当前最重要的结论

不要下一步就直接硬写真实 `llama.cpp` JNI。

更稳的顺序是：

1. 先跑通官方 `llama.cpp` Android 示例
2. 再把其中的 native 层和 Kotlin 封装迁到自己的项目

原因：

- `llama.cpp` 的 `libllama` API 变化较快
- 官方已经提供 `examples/llama.android`
- 直接复用官方示例，比从零手搓 JNI 更稳

官方参考：

- Android 文档：<https://github.com/ggml-org/llama.cpp/blob/master/docs/android.md>
- 仓库：<https://github.com/ggml-org/llama.cpp>

## 明确建议的下一步

下次继续时，按这个顺序进行：

1. 下载 `llama.cpp` 仓库
2. 在 Android Studio 中打开 `examples/llama.android`
3. 先把官方 demo 跑到手机上
4. 看懂它的关键目录、Kotlin 封装、native 组织方式
5. 再回到 `My Application` 项目，把成熟部分迁入自己的工程

不要先做：

- 云端服务
- speculative decoding 协议
- NPU 优化
- GPU/NPU 自动切换

这些都必须在本地真实模型稳定跑通之后再做

## 后续总路线

完整路线已经明确为：

1. Android 环境与真机部署
2. Kotlin/Compose App 骨架
3. ViewModel 状态管理
4. JNI 骨架
5. 接入官方 `llama.cpp` Android 示例
6. 在自己项目中接入真实本地模型
7. 支持模型文件选择与加载
8. 接入云端普通推理接口
9. 再实现手机 draft + 云端 verify 的 speculative decoding

## 下次恢复工作时的开场提示

下次可以直接对 Codex 说：

`继续按照 ANDROID_APP_CHECKPOINT.md，从 llama.cpp 官方 Android 示例接入开始。`

或者更具体：

`阅读 ANDROID_APP_CHECKPOINT.md，然后带我把 llama.cpp/examples/llama.android 跑通。`
