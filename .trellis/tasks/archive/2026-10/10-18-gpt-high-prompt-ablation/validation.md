# 适配阶段验证

- 原始回归：新增配置/HTTP测试 2 failed（字段缺失）；实现后相关 58 passed，扩展多轮和冻结漂移后 60 passed。
- 首次 static 暴露 httpx/httpx2 client 联合赋值类型差异，改为在各具体 client 安装同一 hook，保留类型边界；未加 cast/ignore。
- static：Ruff 通过、mypy 128 source files 通过、312 passed；Provider/OAuth/query/completion/capabilities 80 passed。
- 全量：1155 passed, 1 skipped（25.87s）；随后新增两项测试相关 60 passed。
- 实际账号目录确认 gpt-6.1-sol；目录读取不计推理 HTTP 预算，未执行推理。
- Runtime、Router、Planner Mock HTTP 序列化均 high + summary auto；失败也计数；多轮 2 次真实 Mock transport sends；超额前拒绝；新 budget 实例不能重置总量。
- 捕获移除隐藏 reasoning replay，保留公开 effort 与可见 function_call_output；冻结实际 provider projection 并拒绝 effort drift。
- 生产 Prompt 20450 字符，未修改。

## 真实执行与最终门禁

- `freeze-baseline` 实际 exit1：dev-lexical-chatlog-alpha@v2，HTTP1/120，9534ms，0工具/0rounds，Finalizer skipped，Usage/费用unknown。请求真实 high+summary auto；HTTP200 后 response.metadata / union_tag_invalid / MALFORMED_STREAM，未看到 completed。
- 后续3条以及B/C未执行；保留原始 failure artifact/Trace，未重试、未换Provider、未绕过SSE校验；生产20450字符保持。
- 只读 semantic_status：473236 indexed/canonical messages、54267 chunks，persisted chunker-v1 与 configured v2-forward 不同，stale；未改旧index。
- 新真实 Failure Case 回归：failed baseline 复用测试1 red后修复为green；原真实artifact离线调用当前verify同样拒绝，HTTP计数仍1/120。
- 最终 `static`：Ruff通过、mypy128 source files通过、404 passed（7.95s）。
- 最终全量 `uv run --all-extras pytest -q`：1160 passed, 1 skipped（26.36s）。
- `git diff --check`通过；实验结果经git check-ignore确认ignored，未暂存私有实验文件。
- 本轮工程检查通过，Prompt质量与完整Provider兼容性门禁未通过；按用户定义停止条件交付阻塞报告，不发布精简Prompt。
