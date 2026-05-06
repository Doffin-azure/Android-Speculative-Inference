# 2026-04-29 Qwen 统一配置投机解码实验记录

## 实验目的

本组实验用于对齐端侧本地目标模型推理、云侧本地单进程投机解码、云侧本地双进程投机解码和 Android--桌面端跨设备投机解码四类方案。实验约束包括：

- 云侧本地双进程投机解码应接近云侧本地单进程投机解码。
- Android--桌面端跨设备投机解码不应相对云侧本地双进程投机解码明显劣化。
- Android--桌面端跨设备投机解码应相对 Android 端侧本地运行 7B 目标模型取得至少 30% 加速。

## 统一配置

| 项目 | 配置 |
| --- | --- |
| 草稿模型 | `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` |
| 目标模型 | `Qwen2.5-7B-Instruct-Q4_K_M.gguf` |
| 最大输出 | 1000 tokens |
| 上下文长度 | `ctxSize=2048` |
| 投机提案上限 | `NMax=4` |
| 最小提案长度 | `NMin=1` |
| 草稿概率阈值 | `PMin=0.55` |
| 统计口径 | 会话与运行时准备完成后的稳态墙钟时间 |

统一提示词：

```text
Write a detailed, continuous technical explanation of speculative decoding for about 1000 tokens. Cover motivation, workflow, acceptance, rejection, system overhead, and deployment tradeoffs. Do not stop early.
```

线程口径说明：

- 云侧本地单进程和云侧本地双进程方案均在桌面端运行草稿与目标验证，使用桌面端 8 线程。
- 跨设备方案由 Android 端运行草稿模型，桌面端只执行目标验证，因此桌面端目标验证使用 10 线程。

## 数据来源

| 方案 | 数据来源 |
| --- | --- |
| Android 端侧本地目标模型推理 | `logs/android_local_app_output_2026-04-29T17-06-25+08-00.txt` |
| 云侧本地单进程投机解码 | `reference/spec-split-demo-project/experiments/2026-04-29/recorded_run_2026-04-29T17-44-40+08-00.json` 的 `baseline` 字段 |
| 云侧本地双进程投机解码 | `reference/spec-split-demo-project/experiments/2026-04-29/recorded_run_2026-04-29T17-44-40+08-00.json` 的 `nativeFull` 字段 |
| Android--桌面端跨设备投机解码 | `logs/android_spec_split_app_output_2026-04-29T17-58-05+08-00.txt` |

## 核心结果

| 方案 | 输出词元数 | 接受率 | 平均每轮提案词元数 | 平均每轮接受词元数 | 吞吐率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Android 端侧本地目标模型推理 | 1000 | -- | -- | -- | 7.232 token/s |
| 云侧本地单进程投机解码 | 1004 | 65.86% | 2.525 | 1.663 | 15.707 token/s |
| 云侧本地双进程投机解码 | 1002 | 60.76% | 3.272 | 1.988 | 14.816 token/s |
| Android--桌面端跨设备投机解码 | 1000 | 72.92% | 2.335 | 1.703 | 13.996 token/s |

## 分项耗时

| 方案 | 草稿侧平均耗时 | 验证侧平均耗时 | 说明 |
| --- | ---: | ---: | --- |
| 云侧本地单进程投机解码 | 27.445 ms | 141.630 ms | 单进程内草稿生成与目标验证 |
| 云侧本地双进程投机解码 | 33.231 ms | 154.827 ms | 草稿侧为 `sync + tail refresh + generate`，验证侧为 `comm + decode + sample` |
| Android--桌面端跨设备投机解码 | 59.481 ms | 133.230 ms | 草稿侧为 Android `draftFetchMs`，验证侧为桌面端 `remoteMs` |

跨设备方案共 370 步，`totalMs=71450 ms`，按总耗时计算的平均步耗时为 193.108 ms。草稿侧与验证侧平均耗时之和为 192.711 ms，差额来自本地应用、请求组织和统计取整等零散开销。

## 约束检查

| 比较项 | 计算 | 结果 |
| --- | --- | ---: |
| 云侧本地双进程 / 云侧本地单进程 | 14.816 / 15.707 | 94.33% |
| 跨设备 / 云侧本地双进程 | 13.996 / 14.816 | 94.46% |
| 跨设备相对 Android 端侧本地目标模型推理提升 | 13.996 / 7.232 - 1 | 93.5% |

结论：本组配置满足三项实验约束，可作为论文第5章的主要实验数据。
