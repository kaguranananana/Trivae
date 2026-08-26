# ChatLab Main Baseline

## Source state

- 仓库：`ChatLab/ChatLab`
- 审计分支：当前 `main`
- 审计 commit：`333c913de0fc4c23bfd4f406dc810a9a9f0921b0`
- commit 日期：2026-08-26

实际读取了用户指定的 tool definitions/types/limits、preprocessing/compression 与 desktop agent runner 文件，没有依赖旧文档推断。

## Confirmed design

### Lexical / deep lexical

- `search_messages` default limit：1000。
- `deep_search_messages` default limit：1000。
- 两者 hard cap：50000。
- runtime 注入的 `maxMessagesLimit` 可进一步收紧。
- trim 使用 hit-preserving 语义，避免 context 占用 direct-hit 容量。

### Semantic

- default max results：10。
- hard cap：20。
- runtime 仍会 clamp 到该边界。
- semantic budget 与 lexical 1000/50000 明确分离。

### Tool Result

- compression 配置默认 `maxToolResultPercent=50`。
- desktop runner 根据模型 context window 计算 Tool Result token 容量。
- 超预算会显式 truncated，并提示 Agent 缩小关键词或时间范围后继续检索。

## Adaptation decision for Trivae

- 采用 ChatLab 的“candidate budget != model-visible Tool Result budget”原则。
- lexical default 对齐 1000，但 hard cap 不机械照搬 50000：真实 Trivae archive 最大常见 broad hit 数和 SQLite 实测支持更保守的 5000。
- semantic 采用 10/20，保留 Trivae 的 `dense_top_k=40` 与内部候选逻辑。
- Trivae 尚无可靠模型 context-window registry，因此不复制动态 50%；保留 fixed 16k。
