# 审计与规划验证（2026-10-05）

## 本轮交付与状态

- 基线 `460259d`，初始 main 工作区干净。
- 完成 P01–P92 逐条审计、PRD、design、implement 与后续 context manifests。
- 审计是 planning 阶段产物；尚未修改产品源码、测试、SDK Schema、Provider 请求或 Finalizer。任务保留 planning，等待最终规划评审，不提前 start/归档。
- 下一批建议仅 Markdown 分层、策略去重和已有承接说明压缩；JSON mode 生成契约保留。迁移标签不是实施完成标志。

## 真实执行的检查

### Prompt / SDK 实物核验

`uv run --all-extras python` 导入当前 SYSTEM_PROMPT，实测 `len(SYSTEM_PROMPT)=20450`。直接构造六个生产 SDK adapter 的 FunctionTool，传 trusted_max_results=5000 并读取 params_json_schema/strict_json_schema。无 Provider 请求、无 Capability invocation。

实际结果：六工具均 strict=false；lexical/recent max=5000、semantic max=20、member/SQL max=100；context 默认 8/8，身份均 optional 且无 oneOf；字符串无 minLength、context/dense_top_k 无 minimum、time_range/cursor 为自由 object。Host 真实校验通过对应源码定位，没有假定这些规则已经下沉到 Provider Schema。

### Provider-free 契约 baseline

```bash
# 实际执行成功的命令；覆盖 SDK、Runtime、来源/时序、预算、Finalizer、时间窗/零结果和 SQL。
uv run --all-extras pytest -q tests/test_agent_tool_surface.py tests/test_agent_runtime.py tests/test_context_source_contract.py tests/test_temporal_relation_regression.py tests/test_retrieval_budget.py tests/test_evidence.py tests/test_temporal_overview_coverage.py tests/test_temporal_zero_result_integration.py tests/test_recent_messages.py tests/test_sqlite_read.py
```

结果：**145 passed in 2.00s，exit code 0**。这证明当前契约 baseline 可运行，不证明重构后的模型行为等价；本轮无候选产品实现、无新真实 Provider 配对、未执行全量 pytest/Ruff/mypy。

首条命令误引用不存在的 `test_temporal_overview.py`，pytest exit code 4、no tests ran。通过 `rg --files tests` 定位实际文件后改用 `test_temporal_overview_coverage.py`，并纳入 recent/zero-result/SQL 相关文件重跑。是命令路径错误，不是实现或 assertion 失败；未改测试。

### 文档与范围检查

实际 Python 检查结果：P01–P92 ID 连续、每条有合法标签、交叉引用的 Policy ID 存在、覆盖字符串 L7–230 全部 **224 行**，**27 个**本地文件链接全部可解析，PRD 无 TBD、JSONL context 引用均存在，task 状态为 planning。`git diff --check` 和产品范围 `git diff --quiet HEAD -- src tests evaluation` 均 exit code 0。

`task.py validate .trellis/tasks/10-05-prompt-policy-audit` exit code 0，两个 context manifest 各 5 条有效记录。脚本提示既有 agent-runtime-guidelines.md 为 64,762 bytes，超过自动注入单文件 32,768 bytes；后续子代理必须按需要读取原文件相应完整章节，不能只依赖被裁剪的注入。该提示不改变本轮审计结果，也不通过改注入预算解决。

## Spec 沉淀判断

参考 `trellis-update-spec` 检查了新知识归属。现有 runtime/temporal/quality spec 已定义 Host 时间、source identity、软 Plan、Finalizer 和评测边界；本轮无新的已实施或已确认契约，因此**不修改正式 spec**。Schema 缺口、JSON mode 与语义反例记录在 research/design，避免把待评审迁移写成既成规范。

## 完成边界

本轮只能声称“审计与规划已提交”。不能声称 Prompt 已压缩、token/latency 改善、模型质量提高、Schema 迁移完成或整个重构任务完成。推送状态以 git push 实际退出码为准。
