# 执行顺序

1. 审计架构、现有 artifact、三条 zero Case 与候选 positive/control；写 Failure Case 证据。
2. 在 Evidence/Runtime 主链路做证据支持的最小修复与 deterministic tests。
3. 建 Suite、adjudication schema/template、Router utility analysis 与本地 preflight。
4. 增加 opt-in paired 顺序平衡和 manifest 身份测试。
5. 对齐 ADR、总状态和 evaluation 文档。
6. 跑 focused 与完整 pytest、Ruff、mypy、diff check；修复主链路问题。
7. 估算每对最坏 invocation，按 20～30 次 targeted Phase B 验证；仅满足明确 Phase C 条件才追加，总数不超过 60。
8. 汇总 measured 与未裁决边界，提交本地工作，不 push，核对 clean status。
