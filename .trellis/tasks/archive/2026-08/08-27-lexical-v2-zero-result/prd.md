# PRD: Close mixed-script lexical recall + recent-message empty-result gaps

## 真实基线（HEAD 9c3b7bd）与提示差异确认

- bigram v1 已在 HEAD（strategy `unicode61+cjk-bigram-v1`），`推荐` 窗口 0→157 已验证。
- B1 怀疑成立（待复现）：SDK schema 全参数可选 → `{}` 合法，但 `GetRecentMessagesInput.__post_init__` 拒绝无时间输入。
- B2 怀疑成立（待复现）：final 契约 `ModelAnswerCandidate.requires claims`，honest zero-result → finalization failed。
- A1 提示中的目标语义 `推荐这个repo → 推荐荐这 这个repo` 与现状不同：v1 对 len==2 的 Han run 替换结果等于原文，且不插入 Han/ASCII boundary —— 以实验为准。

## Failure Case 定义

### FC-A：mixed-script lexical miss
unicode61 把 ASCII+Han 粘连串切成单 token；v1 bigram 只重写长度≥2 run 且不建立 Han/ASCII 边界，
len==2 run 归一化后不变 → 边界两侧仍粘连。典型：`abc推荐`/`推荐abc`/`repo推荐这个`。

### FC-B：合法空窗查询被 final contract 升级为 terminal failed
Tool ok + coverage complete + 0 messages 是合法业务结果；`claims=[]` 被
ModelAnswerCandidate/AnswerArtifact 双层拒绝；无 no-result 出口。

## Requirements

- 保留 FTS5 主路径、bigram 方向、recent 链路、Evidence/Citation/Trace、tool selection 架构。
- 禁 LIKE 主路径/fallback/merge、外部搜索服务、第二套 provenance、keyword Router。
- v2 normalization：Han run ≥2 → 包裹边界空格的重叠 bigram；单 Han 字保留并包边；ASCII 内部不动。
- strategy bump v1→v2；mismatch 显式 stale，要求 rebuild，禁止隐藏 fallback。
- get_recent_messages({}) ≡ relative recent 2 days anchor=archive_latest（不用 wall clock）；SDK=Capability 一致。
- no-result finalization：显式候选形态（kind=no_result + summary + limitations），Host 用 ToolResultRecord
  可验证“确无可引用数据”才接受——有 message/row facts 时拒绝该候选，防止 citation bypass。
- Evaluation：temporal-overview 与 empty-window 进入确定性 ScriptedModel pytest 回归（first-tool 选择依赖真实模型，
  由真实 smoke 取证）；case 文件保持 seed 定位并如实报告。

## Acceptance

见用户验收标准 1–20；全部以真实运行输出为准。
