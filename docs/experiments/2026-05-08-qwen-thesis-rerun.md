# 2026-05-08 Qwen 统一配置资源占用复跑记录

## 使用结论

本次复跑的吞吐表现低于 2026-04-29 的论文正文版本，因此正文吞吐实验结果继续采用 2026-04-29 的数据。本文件保留本次复跑得到的内存占用观测，作为论文中资源占用补充分析的依据。

## 实验配置

| 项目 | 配置 |
| --- | --- |
| 草稿模型 | `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` |
| 目标模型 | `Qwen2.5-7B-Instruct-Q4_K_M.gguf` |
| 最大输出 | 1000 tokens |
| 上下文长度 | `ctxSize=2048` |
| 投机提案上限 | `NMax=4` |
| 最小提案长度 | `NMin=1` |
| 草稿概率阈值 | `PMin=0.55` |
| 云侧本地线程 | 8 |
| 跨设备目标验证线程 | 10 |

统一提示词：

```text
Write a detailed, continuous technical explanation of speculative decoding for about 1000 tokens. Cover motivation, workflow, acceptance, rejection, system overhead, and deployment tradeoffs. Do not stop early.
```

## 数据来源

| 方案 | 数据文件 |
| --- | --- |
| Android 端侧本地 7B 目标模型推理 | `reference/spec-split-demo-project/experiments/2026-05-08/android_local_summary_2026-05-08T15-16-18+08-00.json` |
| 云侧本地单进程投机解码 | `reference/spec-split-demo-project/experiments/2026-05-08/recorded_run_2026-05-08T15-44-38+08-00.json` 的 `baseline` 字段 |
| 云侧本地双进程投机解码 | `reference/spec-split-demo-project/experiments/2026-05-08/recorded_run_2026-05-08T15-44-38+08-00.json` 的 `nativeFull` 字段 |
| Android--桌面端跨设备投机解码 | `reference/spec-split-demo-project/experiments/2026-05-08/android_spec_split_summary_2026-05-08T15-38-32+08-00.json` |

## 吞吐结果，仅作复跑记录

| 方案 | 输出词元数 | 接受率 | 平均每轮提案词元数 | 平均每轮接受词元数 | 吞吐率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Android 端侧本地目标模型推理 | 1000 | -- | -- | -- | 8.279 token/s |
| 云侧本地单进程投机解码 | 1004 | 65.86% | 2.525 | 1.663 | 16.182 token/s |
| 云侧本地双进程投机解码 | 1002 | 60.76% | 3.272 | 1.988 | 14.862 token/s |
| Android--桌面端跨设备投机解码 | 1000 | 72.92% | 2.335 | 1.703 | 13.230 token/s |

## 分项耗时，仅作复跑记录

| 方案 | 草稿侧平均耗时 | 验证侧平均耗时 | 吞吐率 |
| --- | ---: | ---: | ---: |
| 云侧本地单进程投机解码 | 26.468 ms | 138.068 ms | 16.182 token/s |
| 云侧本地双进程投机解码 | 33.686 ms | 153.493 ms | 14.862 token/s |
| Android--桌面端跨设备投机解码 | 68.578 ms | 135.097 ms | 13.230 token/s |

说明：云侧单进程验证侧耗时为 `averageVerifyDecodeMs + averageVerifySampleMs`；云侧双进程草稿侧耗时为 `sync + rollback + tail refresh + generate`，验证侧耗时为 `comm + decode + sample + rollback`；跨设备草稿侧与验证侧分别取 Android 日志中的逐步 `draftFetchMs` 和 `remoteMs` 均值。

## 约束检查，仅作复跑记录

| 比较项 | 比例或提升 | 结论 |
| --- | ---: | --- |
| 云侧本地双进程 / 云侧本地单进程 | 91.84% | 低于论文正文采用的 2026-04-29 版本 |
| 跨设备 / 云侧本地双进程 | 89.02% | 低于论文正文采用的 2026-04-29 版本 |
| 跨设备相对 Android 端侧本地目标模型推理提升 | 59.8% | 高于 30% 加速约束，但不作为正文采用结果 |

## 内存采样记录

内存采样用于资源占用观察。Android 侧采用 `dumpsys meminfo com.example.myapplication` 的 `TOTAL PSS`；桌面侧采用 Windows 进程工作集，包含 `vmmemWSL`、`desktop_target_runtime.exe` 等实验相关进程。云侧本地方案的桌面工作集包含 WSL 运行时基础占用，因此用于同机复跑的相对观察，不等价于模型独占 RSS 或独占显存。

其中，Android 端侧本地 7B 目标模型推理保留为内存占用基线，用于观察端侧直接加载大模型时的资源压力。

| 方案 | Android 峰值 PSS | Android 平均 PSS | 桌面峰值工作集 | 桌面平均工作集 |
| --- | ---: | ---: | ---: | ---: |
| Android 端侧本地目标模型推理 | 4618.2 MB | 3979.5 MB | -- | -- |
| 云侧本地投机解码 | -- | -- | 10329.1 MB | 9100.4 MB |
| Android--桌面端跨设备投机解码 | 590.6 MB | 546.4 MB | 9986.1 MB | 8039.3 MB |

内存对比图见 `docs/experiments/2026-05-08-qwen-memory-comparison.svg`。
