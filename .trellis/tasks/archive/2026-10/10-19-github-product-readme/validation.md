# 验证与交付记录

## 成品
- README 产品定位、真实预览、6 个功能、3 个场景、准确 Mermaid、5 个工程亮点、Quick Start、文档导航、隐私与许可。
- docs/getting-started.md、configuration.md、architecture.md、evaluation.md、product-preview.md、third-party-notices.md；3 张真实 UI 截图及 ChatLab 第三方许可副本。
- 旧 README 中的 OAuth、多账号、Jev、索引重建/续建、真实验证脚本与 Variant 限制已迁移；真实群聊标识示例改为占位。
- 只读审查当前实现与最近提交；GPT High Prompt 精简候选最终拒绝，不宣传实验收益；引用 degraded 与可信边界 fatal 准确区分。

## 实际验证
- uv sync --extra dev --extra semantic --locked --dry-run：90 packages，无需环境修改。
- pnpm -C web install --frozen-lockfile、build、lint、typecheck：exit 0。
- pnpm -C web test：12 files / 69 tests passed；Node localStorage 实验提示不影响结果。
- uv run ruff check src tests：pass；uv run mypy src：128 source files pass。
- 后端相关测试 179 passed：evaluation/query_execution_core/evidence/planner_engineering_closure 93；cli/web_server/web_streaming_contract/ingestion/import_index_updates/application_retrieval 86。
- Evaluation Case validate：13 valid；eval regression 可执行。
- 63 个文档相对链接与锚点、17 种 CLI 参数形态通过复核，fence 与 diff whitespace 检查通过。
- 独立临时 Canonical 库实际导入 5 条合成消息并重建 FTS5；实际 Web→API→Application→DeepSeek Runtime→lexical_search→回答与 4 个来源。只拍真实界面，不提交临时库/原始 Trace。
- ChatLab 上游 AGPL-3.0 许可证原文与本地副本直接内容比较一致；未添加 Trivae 整体许可证。

## About
通过 gh repo edit 实际更新 Description 和 7 Topics，随后 gh repo view 回读一致；visibility 保持 PRIVATE。Description：Local-first AI agent for searching and analyzing high-noise group conversations, with hybrid retrieval and evidence-grounded answers.
Topics：ai-agent, rag, chat-analysis, information-retrieval, sqlite, fastapi, llm-evaluation。

## 公开风险
本地只读审查覆盖任务开始时 2,581 个跟踪文件、414 次提交及 11,187 个可达唯一 blob。未识别高置信度有效凭据，但存在真实实验聊天证据/来源身份、跟踪数据库和 Trace，以及第三方面试资料中的未遮盖联系方式。历史仍有副本，不能声称已脱敏。详细位置与安全分类保存在 ignored tmp/publication-audit.md，未把匹配正文或凭据加入新文档。
ChatLab 过程分段存在明确来源继承；已补充声明与许可副本，整体分发许可及完整适用范围仍待维护者确认。未删除文档、数据库或历史，未修改可见性。

## Spec judgment
本任务仅改文档；没有新增/变更 API、Schema、Provider 或核心行为，现有执行合同不变。首次导入需要索引、引用降级语义已在上手/架构文档记录，无需复制到新 spec；没有额外架构决策。

## 交付边界
用户明确要求本轮仅本地提交，不 Push。保留 .opencode/package.json、现有 import-once lock、未命名.base 等原有改动。工作提交在先，归档与 journal 在后。

工作提交：559e2e4 — docs: productize README and GitHub project presentation。
