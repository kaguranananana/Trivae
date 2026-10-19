# 脱敏实验交付终审

终审范围：`experiment-report.md`、`results-summary.json`、`candidate-edits.json`。独立 Codex Agent 模型审查，非人工裁决；未向 Trivae 被测 Provider 增发 Judge 或实验请求。仅新增本复核记录，未修改报告、代码、实验工件或 GT。

## 结论

未发现影响当前“部分完成、TLS 外部阻塞、保留生产 Prompt”结论的事实或统计错误。三个文件的预算、运行计数、已知 Usage 下界、候选字符/父链、配对方向和发布限制一致。以下两处建议由主任务收窄文字以避免过度概括；本 Agent 不直接修改被审文件。

## Findings (not fixed)

1. `experiment-report.md` 第一节“本轮实际实验均使用该运行代码，后续只有脱敏文档变化”建议明确为“**修复后的 Prompt 质量运行均使用 b669bcc 的生产代码**”。原失败、修复前 strict reproduction 在摘要中明确对应旧提交，属于正确保留的诊断历史；原句若把这些也包含在“本轮实际实验”，会与机器摘要旧版本身份产生歧义。生产代码未在后续质量运行中变更这一核心事实成立。
2. 第二节“验证各 metadata 与最终响应 ID 一致”建议改成“验证同流 metadata 身份一致，并与 **completed Response** ID 一致”。实际实现只对已知 metadata 之间以及 completed 响应做该关联检查；failed/incomplete 仍走原显式错误分类，不宜将已实现检查泛指所有失败终态。无需改实现或扩大校验。

## 核验事实

- `results-summary.json` 中 26 个去重运行的 HTTP、Prompt 字符、终态、Usage 与耗时逐条匹配原始私有 artifact。新派生快照按 run_id 去重为 23 条运行、11 completed；8 个 Case 至少发送过一次被测 Provider 请求。别名文件不重复计数，旧协议诊断/组件回归不冒充新快照质量样本。
- 全部 20 份 phase ledger 的 provider_calls 合计 52，与原 total ledger 52/120 一致，剩余 68。新派生阶段运行 artifact 发送合计 44，其余是原失败/协议与组件诊断；认证失败或 phase 发送前阻止仍为 0 实验 HTTP。
- 已知运行 Usage 为 38 次，加严格诊断 wire 的 1 次和 Router 完整响应的 1 次，共 40 次；输入 479227、输出 7155、总量 486382、缓存 14720、推理 913，独立加和一致。剩余 12 次未知；金额 null，没有以 0 或公开标价伪装真实成本。
- 候选按每个 parent 逐段删除整串重建，字符依次为 20450→20415、B02=20251；C01 从 B01 分支为 19854，C02 从 C01 为 19764。P56/P57 在实际 C 系列保留，P33 不因累计局部改善独立接受。2.9144% 仅为待续候选字符下降，生产删减仍为 0。
- 仅 B01 SQL、C01 TS、累计 C02 book 构成有效质量配对，持平1/改善2/退化0限于此分母；A TS 未送达指定 target、A book 未恢复具体材料均如实保留。父 C01、UI、精确 A、累计门禁和最后四条的缺口不改记通过，不用失败配对推导质量退化。材料 Case 的 reference_findings 为空及其 Agent/Canonical witness 审查边界明确。
- 报告明确人审/原 review_policy pending、Agent 模型复核非人工盲审，未向被测 Provider 加 Judge 请求；TLS 阻塞停止、任务待续、不归档全部完成、生产完整 Prompt 保留，均一致。
- 逐字阅读并检查三个文件：无私有消息正文、Canonical 群/消息/作者定位符、私有绝对路径、OAuth 凭据或密钥。公开候选删除片段来自生产 Prompt，不是私有聊天内容。机器摘要只保留公开 Case 名、运行关联身份及脱敏指标，没有复制源定位或 Tool Result。

## Verification

- 只读原始指标与摘要逐项比较：通过。
- phase/总账与 Usage 下界独立求和：通过。
- 候选 parent/删除片段/字符整串重建：通过。
- 隐私人工阅读与 Canonical locator / secret / 私有路径模式扫描：通过。
- 未改生产代码，未重复执行工程测试；原 68 项协议、245 项合同与已记录全量/静态验证继续按各自原记录表述，不将文档终审包装成再次测试通过。

主任务已修正两处文案：代码身份限定为修复后质量运行，metadata身份核对限定为同流metadata与completed；机器摘要另逐run记录原commit，不把旧失败写成b669运行。公开指标与发布结论未变。

终审后仅为metadata关键行补充中文解释，主任务验证其AST与b669bcc完全等价并通过Ruff；没有调整协议、预算、工具或评测行为，报告已如实注明。
