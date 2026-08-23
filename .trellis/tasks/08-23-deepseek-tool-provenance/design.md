# 技术设计：DeepSeek Tool Calling 与 Provenance Failure

## 最小行为差距

当前 DeepSeek Provider 能完成无工具调用，但真实聊天检索 Query 曾出现 `INVALID_ARGUMENT` 和 `UNRESOLVED_MESSAGE_SOURCE`。目标行为是：模型只产生符合现有 Tool contract 的调用，并且最终回答只能引用当前 Run Tool Result 中真实存在的来源。

## 责任边界

- `SearchMessagesInput` / Capability：继续拥有业务字段与 trusted scope 校验；不接受模型兼容性名义下的隐式修正。
- `openai_tools.py`：拥有 SDK Function Tool 类型转换、provider-facing description、safe Tool Result provenance projection；必要时在此补充脱敏诊断。
- `openai_adapter.py` / `prompt.py`：拥有 DeepSeek/OpenAI-compatible schema 与模型行为约束；不执行业务校验或 citation repair。
- `evidence.py`：继续拥有 deterministic parse、current-run locator、scope validation 和 trusted hydration；不猜测或相似匹配消息。
- Trace：记录事实与归因，不驱动业务执行；debug 诊断必须排除 secret、hidden reasoning 和越权数据。

## 调查路径

1. 使用临时 SQLite 与复制的真实 raw 数据重现真实 Provider Query。
2. 用 debug Trace 保留 bounded tool request、tool result provenance、finalization error；必要时在测试/临时 smoke harness 中捕获 SDK function wrapper 收到的 JSON-safe 参数，不把原始 provider payload 写入仓库。
3. 对每个 Tool Call 分类为 SDK schema decoding、`SearchMessagesInput` 构造/contract、Capability/Retrieval 或未知 adapter 异常。
4. 从本次 Runtime final output 解析模型提交的 message source locator，与 `RuntimeResult.tool_results` 的 current-run provenance 做精确 tuple 比较。
5. 检查 hits 与 expanded context 是否都进入 `ToolResultRecord` 和 `to_model_provenance()`；若已覆盖，则不把 unresolved citation 归因于 Retrieval。

## 候选方案与选择门槛

1. 增强 Function Tool schema/description：仅当证据显示字段类型、空列表或边界约束未被模型稳定理解时采用。
2. 补充 system prompt：仅补模型真正缺失的行为规则，例如 keyword 是单一 string、未使用 optional filter 时省略而非空数组。
3. Provider-facing adapter：仅当真实请求/SDK schema 证明 DeepSeek OpenAI-compatible 适配存在格式差异时采用；不改变业务 contract。
4. `source_ref` Reopen：仅当字段逐一存在但 DeepSeek 反复搬运完整 locator 时采用；必须新增 ADR Reopen 记录和 current-run 唯一映射测试。

## 明确不做

- 不放宽 keyword、list、timestamp、limit、context window 或 ExecutionScope contract。
- 不自动交换时间范围、clamp 数字、删除非法字段、重试模型或把裸文本包装成成功 AnswerArtifact。
- 不在 Finalizer 中相似匹配消息、猜测 locator、接受未知 source_ref 或删除 invalid citation。
- 不引入新的 Evidence Tool、Evidence Agent、队列、外部 observability 基础设施或第二套执行循环。

## 关键逻辑说明

工具参数在 SDK wrapper 进入 `SearchMessagesInput` 时记录一次安全投影，随后由现有 contract 决定接受或拒绝；失败仍返回原有 `INVALID_ARGUMENT`，不改变错误语义。最终 citation 只在 current-run `ToolResultRecord` 索引中精确命中时 hydrate；任何字段缺失、串源或未知 locator 继续返回 `UNRESOLVED_MESSAGE_SOURCE`/相关 provenance error。
