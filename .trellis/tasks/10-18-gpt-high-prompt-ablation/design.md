# 设计与边界

最小缺口：Responses 仅 summary=auto；Screening 假定传统 client 导致 GPT 无法安装 HTTP 计数。配置归 ModelSettings，精确支持能力归 model_capabilities，Responses Model 在统一 payload/projection 使用相同 effort，Runtime/Router/Planner 共用 Model。保持未配置时历史语义，只显式允许本轮已请求的 high 精确模型组合。

实验专用 ScreeningRuntime 将同一 ProviderCallBudget hook 安装到实际 HTTP client；多轮和 completion 共用该边界，保留既有 hooks。请求保存只留公开 effort/summary，剔除历史 reasoning item 与 encrypted_content。Frozen conditions 增加实际请求投影，任何配置/工具/snapshot 漂移拒绝复用。真实输入、答案、Trace、usage 沿用现有 Evaluation。

## 七问
- Responsibility：显式 effort 与实验预算/身份，不创建 runtime/eval 分支体系。
- Failure Cases：非法组合、GPT client=None、多轮漏计、预算耗尽、历史 reasoning 泄漏、旧 freeze 漂移。
- Observability：安全配置、HTTP ledger、原始本地 artifact、Trace 和独立语义 review。
- Attribution：参数属于 configuration/provider；漏计属于 harness；证据已到而概括错属 generation。
- Decision：在实际 httpx hook 承接既有预算，避免 SDK method 级计数遗漏 transport attempts。
- Verification：Mock HTTP 序列化/多轮/失败/超额；相关回归、静态、全量 pytest；真实 Provider smoke。
- Regression：新增精确配置、SDK HTTP、冻结漂移和隐私断言，保留所有真实失败。

候选沿用 92 Policy ID：B 先一项机械说明删除，再逐项累计；C 每次一组策略，不能先累计未验证策略。作者、时间、权限、provenance、强否定、输出契约默认保留。评审为本会话人工式语义复核，非独立盲评；不宣称全新 Holdout。
