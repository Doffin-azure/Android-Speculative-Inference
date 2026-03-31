# Speculative 解码实现指南（中文）

## 文档目的

这份文档面向当前项目的下一阶段实现。

目标不是再解释“为什么要做 speculative”，而是把它具体落到当前工程里：

- 手机端需要新增什么能力
- 电脑端需要维护什么会话状态
- 协议具体传什么
- 第一版代码应该先写到哪里
- 哪些部分先做骨架，哪些部分后做优化

这份文档建立在当前已经完成的两条基线上：

1. Android 本地推理已验证成功
2. Android 到电脑的普通远程推理已验证成功

因此，speculative 解码在本项目里应被视为：

- 构建在“本地基线 + 普通远程基线”之上的第三层
- 不是替代这两条基线
- 必须始终保留 fallback

## 一、Speculative 解码的工作思想

Speculative 解码的核心思想可以概括为：

- 手机上的小模型先“打草稿”
- 电脑上的大模型负责“审核”
- 审核通过的 token 直接接受
- 审核不通过的位置由大模型给出修正
- 双方在修正后的共同前缀上继续下一轮

普通解码的模式是：

- 大模型独自生成每一个 token

Speculative 解码的模式是：

- 小模型先提出若干 token 候选
- 大模型不必重新慢慢生成整段，而是尽量“一次确认一小段”

如果小模型和大模型在后续 token 上一致率较高，那么：

- 大模型可以一次接受多个 token
- 每轮有效推进的 token 数增加
- 总体交互延迟下降

## 二、为什么必须做到 token 级

在本项目里，真正可实现的 speculative 解码必须是 token 级，而不能只停留在字符串级。

原因有三点：

1. 字符串一致不代表 token 一致
2. 只有 token 级才能精确表达“接受到第几个 token”
3. 只有 token 级 correction 才能把手机端上下文恢复到和电脑端一致

因此，协议的真实 source of truth 应该是：

- `sharedPrefixTokenIds`
- `proposedTokenIds`
- `acceptedCount`
- `correctionTokenIds`

文本字段只用于：

- 调试
- UI 展示
- 方便日志理解

不应作为验证逻辑的判断依据。

## 三、当前项目里的三层结构

在本项目里，建议长期保留三种运行模式：

1. `LOCAL`
2. `REMOTE`
3. `SPECULATIVE`

三者职责如下：

`LOCAL`

- 手机本地模型完整生成
- 用于离线、调试本地性能、兜底 fallback

`REMOTE`

- 手机发送普通请求
- 电脑完整生成
- 这是当前已经验证成功的普通远程基线

`SPECULATIVE`

- 手机本地 draft 模型先提出 token
- 电脑 target 模型负责 verify
- 一旦 speculative 失败，立即回退到 `REMOTE`

第一版实现时，`SPECULATIVE` 不应移除 `LOCAL` 和 `REMOTE`。

## 四、手机端与电脑端的职责分工

### 手机端职责

手机端负责：

1. 用较小模型生成 draft token
2. 维护本地 speculative session 状态
3. 把 draft token 发送给电脑端
4. 接收 verify 结果
5. 应用 accepted token 和 correction token
6. 必要时退回普通远程生成

### 电脑端职责

电脑端负责：

1. 为每个 speculative 会话维护 target session 状态
2. 接收手机 draft proposal
3. 在相同 token 前缀上验证 proposal
4. 返回 accepted prefix 长度
5. 返回 correction token
6. 在失败时执行普通远程 fallback

## 五、第一版协议建议

当前项目已经有英文草案：

- `docs/project/speculative-decoding-protocol-draft.md`

将其转成更适合实现的第一版接口，建议保留四个核心 endpoint：

1. `POST /v1/speculative/start`
2. `POST /v1/speculative/propose`
3. `POST /v1/speculative/fallback`
4. `POST /v1/speculative/close`

### 1. `start`

作用：

- 初始化电脑端 session
- 固定当前 prompt 前缀
- 返回 session 就绪状态

建议请求体：

```json
{
  "protocolVersion": 1,
  "type": "startSession",
  "sessionId": "sess-001",
  "requestId": "req-001",
  "targetModel": "desktop-target-model",
  "draftModel": "android-draft-model",
  "systemPrompt": "You are a concise assistant.",
  "userPrompt": "Explain speculative decoding simply.",
  "sampling": {
    "temperature": 0.7,
    "topP": 0.9
  }
}
```

建议返回体：

```json
{
  "protocolVersion": 1,
  "type": "startSessionResult",
  "sessionId": "sess-001",
  "status": "ready",
  "error": ""
}
```

### 2. `propose`

作用：

- 手机发送本轮 draft token
- 电脑进行 verify
- 电脑返回 accepted 和 correction

建议请求体：

```json
{
  "protocolVersion": 1,
  "type": "proposeDraft",
  "sessionId": "sess-001",
  "draftStep": 3,
  "proposedTokenIds": [1287, 338, 264],
  "proposedText": "speculative decoding is",
  "maxCorrectionTokens": 1
}
```

建议返回体：

```json
{
  "protocolVersion": 1,
  "type": "verifyDraftResult",
  "sessionId": "sess-001",
  "draftStep": 3,
  "acceptedCount": 2,
  "acceptedTokenIds": [1287, 338],
  "rejectedFromIndex": 2,
  "correctionTokenIds": [991],
  "targetTextDelta": "speculative decoding works",
  "finishReason": "",
  "error": ""
}
```

### 3. `fallback`

作用：

- 当 speculative 无效或出错时
- 手机要求电脑改用普通远程推理继续生成

建议请求体：

```json
{
  "protocolVersion": 1,
  "type": "fallbackGenerate",
  "sessionId": "sess-001",
  "reason": "verification_mismatch_threshold",
  "remainingMaxTokens": 96
}
```

### 4. `close`

作用：

- 显式释放电脑端会话状态
- 结束 speculative 生命周期

建议请求体：

```json
{
  "protocolVersion": 1,
  "type": "closeSession",
  "sessionId": "sess-001",
  "reason": "completed"
}
```

## 六、手机端该怎么实现

### 手机端实现目标

手机端第一版的真正目标不是“先把算法做到最好”，而是：

1. 先形成 session
2. 先能产出 draft token ids
3. 先能应用 verify 结果
4. 先能稳定 fallback

### 手机端需要的核心能力

当前本地推理链路更偏一次性生成：

- 输入 prompt
- 输出文本

要做 speculative，手机端必须新增会话式能力：

1. `startSpeculativeSession(...)`
2. `draftTokens(sessionId, maxDraftTokens)`
3. `applyVerifiedTokens(sessionId, acceptedCount, correctionTokenIds)`
4. `closeSpeculativeSession(sessionId)`

其中最关键的是第 2 和第 3 项。

### 手机端 session 需要保存什么

建议在 app 层先有一个明确的 speculative session state：

- `sessionId`
- `requestId`
- `draftStep`
- `systemPrompt`
- `userPrompt`
- `acceptedTokenIds`
- `lastProposedTokenIds`
- `lastCorrectionTokenIds`
- `acceptedTokenCount`
- `mismatchCount`
- `fallbackReason`
- `status`

建议状态值：

- `Idle`
- `StartingSession`
- `Drafting`
- `WaitingForVerification`
- `ApplyingAcceptedTokens`
- `FallingBack`
- `Completed`
- `Error`

### 手机端 draft token 如何产生

第一版目标是让本地引擎对外暴露“下一批 token ids”，而不是最终字符串。

理想形态是 `:lib` 层最终提供：

- 给定当前 session 前缀
- 生成接下来 `n` 个 token id
- 不破坏 session 上下文

在当前项目里，后续真正需要落到：

- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

第一版不要追求一次产出很多 token。

建议：

- `maxDraftTokens = 1~4`

原因：

- easier to debug
- 更容易比较 accepted prefix
- correction 成本低

### 手机端如何应用 verify 结果

这是 token 级 speculative 的核心。

流程如下：

1. 手机生成本轮 `proposedTokenIds`
2. 电脑返回 `acceptedCount`
3. 手机只提交 proposal 的前 `acceptedCount` 个 token
4. 如果电脑返回 `correctionTokenIds`
5. 手机必须把 correction token 也写入自己的本地 session
6. 下一轮从“accepted + correction”后的共同前缀开始

也就是说，手机不能认为：

- “我自己提议过的 token 就已经算数”

真正算数的只有：

- accepted prefix
- target 给出的 correction

### 手机端伪代码

```kotlin
val localSessionId = draftEngine.startSpeculativeSession(
    systemPrompt = systemPrompt,
    userPrompt = userPrompt
)

remoteClient.startSpeculativeSession(...)

while (!finished) {
    val proposedTokenIds = draftEngine.draftTokens(
        sessionId = localSessionId,
        maxDraftTokens = 3
    )

    val verify = remoteClient.proposeDraft(
        sessionId = sessionId,
        draftStep = step,
        proposedTokenIds = proposedTokenIds
    )

    draftEngine.applyVerifiedTokens(
        sessionId = localSessionId,
        acceptedCount = verify.acceptedCount,
        correctionTokenIds = verify.correctionTokenIds
    )

    uiTokens.addAll(verify.acceptedTokenIds)
    uiTokens.addAll(verify.correctionTokenIds)

    if (verify.finishReason.isNotBlank()) {
        finished = true
    }

    step += 1
}

remoteClient.closeSpeculativeSession(sessionId)
draftEngine.closeSpeculativeSession(localSessionId)
```

### 手机端第一版代码建议落点

建议先在 app 层加 speculative client 和 state，不要一开始就把复杂度塞进 `:lib`。

第一批新增或修改落点建议：

- `app/src/main/java/com/example/myapplication/inference/RemoteInferenceClient.kt`
  增加 speculative endpoints 调用
- `app/src/main/java/com/example/myapplication/viewmodel/MainViewModel.kt`
  增加 `SPECULATIVE` 模式和会话状态
- `app/src/main/java/com/example/myapplication/ui/MainScreen.kt`
  增加 speculative 调试区和状态展示

后续真正 token 级 draft 能力再下沉到：

- `lib/src/main/java/com/example/myapplication/llama/internal/InferenceEngineImpl.kt`
- `lib/src/main/cpp/ai_chat.cpp`

## 七、电脑端该怎么实现

### 电脑端第一版目标

电脑端第一版不追求高性能，只追求：

1. 能维护 session
2. 能接收 token proposal
3. 能返回 accepted prefix 和 correction
4. 能 fallback

### 电脑端需要保存什么

每个 speculative session 至少保存：

- `sessionId`
- `requestId`
- `systemPrompt`
- `userPrompt`
- `status`
- `acceptedTokenIds`
- `draftStep`
- `acceptedTokenCount`
- `mismatchCount`
- `lastCorrectionTokenIds`
- `lastFinishReason`

如果后续实现更深的 target token context，则还需要：

- target model 当前前缀对应的内部上下文
- 或者足以重建该上下文的 token 前缀

### 电脑端 verify 应该怎样做

第一版 verify 不需要追求“高级批量验证优化”，先实现逐 token 验证就够了。

逻辑如下：

1. 电脑从当前 target session 前缀开始
2. 依次检查手机 proposal 的每个 token
3. 若 token 与 target 下一 token 一致，则 accepted
4. 若不一致，则停止接受
5. target 生成一个或少量 correction token
6. 返回 `acceptedCount + correctionTokenIds`

### 电脑端伪代码

```python
def verify_proposal(session, proposed_token_ids):
    accepted = []
    correction = []

    for token_id in proposed_token_ids:
        target_next = target_next_token(session)

        if token_id == target_next:
            accepted.append(token_id)
            session.accept_token(target_next)
        else:
            correction.append(target_next)
            session.accept_token(target_next)
            break

    return {
        "acceptedCount": len(accepted),
        "acceptedTokenIds": accepted,
        "correctionTokenIds": correction,
    }
```

这版很朴素，但非常适合第一轮正确性验证。

### 电脑端为什么必须保留 fallback

当发生下面这些情况时，必须允许立即切回普通远程模式：

- 连续 mismatch
- session 状态不一致
- 手机 draft engine 异常
- token 级能力暂时不可用
- 协议版本不匹配

所以电脑端的 speculative 实现不能孤立存在，必须能复用当前已经跑通的：

- `POST /v1/generate`

### 电脑端第一版代码建议落点

当前最佳落点是：

- `tools/desktop_inference_service.py`

第一版建议先在这里增加：

- 内存 session store
- `/v1/speculative/start`
- `/v1/speculative/propose`
- `/v1/speculative/fallback`
- `/v1/speculative/close`

并且把每一步都写入现有 request log。

## 八、和 `llama.cpp` 现有 speculative 框架有什么关系

本机 `llama.cpp` 里的 speculative 通用框架很有参考价值，但不能直接照搬成我们项目的完整实现。

最值得复用的思想有三类：

### 1. `begin / draft / accept` 生命周期

`llama.cpp/common/speculative.cpp` 里已经把 speculative state 抽象成：

- `begin(prompt)`
- `draft(...)`
- `accept(n_accepted)`

这和我们现在的协议可以很好映射：

- `startSession`
- `proposeDraft`
- `apply accepted / correction`

### 2. target / draft 词表兼容性检查

`llama.cpp` 现有 speculative 代码很强调：

- vocab type 一致
- BOS/EOS 一致
- token 文本尽量一致

这对我们项目非常重要。

如果手机 draft 模型和电脑 target 模型的 tokenizer 明显不兼容，那么 speculative 会很难做稳。

### 3. 统计信息

`llama.cpp` 里 speculative state 有这类统计字段：

- generated tokens
- accepted tokens
- draft calls
- accept calls
- timing

这些统计在我们项目里也非常值得保留，因为后面是否值得继续优化 speculative，关键看：

- accepted ratio
- mismatch rate
- per-step latency

### 当前不能直接复用的部分

`EAGLE3` 虽然在 `llama.cpp` 里已经有类型位，但实现还是空壳。

也就是说：

- `EAGLE3` 这个名字和入口可以参考
- 真正能复用的是通用 speculative 架构
- 不能把 `EAGLE3` 当现成可接入的完整实现

## 九、第一版应该怎样分阶段写代码

### 阶段 1：桌面侧 speculative session 骨架

先做：

- session store
- speculative endpoints
- request log
- fallback

先不要求手机真实 draft token 一定来自本地模型。

目标是先跑通状态机。

### 阶段 2：Android speculative 模式和状态管理

先做：

- `SPECULATIVE` 模式入口
- sessionId
- draftStep
- acceptedCount
- correction 摘要
- fallback 原因

先把 UI 和 ViewModel 状态清楚。

### 阶段 3：本地 draft token 能力接入

这一步才开始补 `:lib` token 级接口。

目标是：

- 从本地 session 中拿到 draft token ids
- 能把 correction token 正确应用回本地上下文

### 阶段 4：真实 speculative 闭环

闭环判断标准：

- 手机发 draft token
- 电脑返回 accepted/correction
- 手机应用 correction
- 下一轮仍然从一致前缀继续
- fallback 始终可用

### 阶段 5：优化

只有在正确性稳定后再做：

- chunk size 调整
- transport 优化
- session 缓存优化
- accepted ratio 分析
- speculative / remote / local 模式切换策略

## 十、当前项目里的推荐实现顺序

结合当前工程状态，最推荐的下一步顺序是：

1. 先改 `tools/desktop_inference_service.py`
   新增 speculative session endpoints
2. 再改 `RemoteInferenceClient.kt`
   加 speculative HTTP 调用
3. 再改 `MainViewModel.kt`
   增加 speculative state
4. 再改 `MainScreen.kt`
   增加 speculative 调试界面
5. 最后再下沉到 `:lib`
   补本地 token 级 draft 能力

这是当前风险最低的路径。

## 十一、第一版完成标准

第一版 speculative 节点完成时，应满足：

- 电脑端可以创建 speculative session
- 手机端可以发 proposal
- 电脑端可以返回 acceptedCount 和 correctionTokenIds
- 手机端可以应用 correction 并进入下一轮
- fallback 到普通远程仍然稳定
- 所有步骤都有 session 级日志

## 十二、总结

在本项目里，Speculative 解码的正确落地方式不是跳过基线直接追求高性能，而是：

- 先把本地基线和普通远程基线当作已成立前提
- 在其上增加 token 级 session 协议
- 先实现最小可调试闭环
- 再逐步优化 chunk、延迟和接受率

一句话总结当前实现原则：

**手机负责 draft token，电脑负责 verify token；手机只提交 accepted 的部分，并把电脑返回的 correction 写回自己的本地 session，然后双方从修正后的共同前缀继续。**
