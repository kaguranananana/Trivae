# 执行计划
1. 审计 Canonical/forward/chunker/store 与 ChatLab 参考，建立相关测试 baseline。
2. 增加 mutation 位置跟踪与安全范围读取；增加精确输入凭据、事务发布与向量复用接口。
3. 集成 builder.update 和自动导入 obligation（不依赖 inserted_count）。
4. 临时库回归、失败/并发/重启、全量对照与 benchmark；真实 Qwen 集成。
5. pytest、ruff、mypy、diff review，更新设计/运维/spec/验证证据。
6. 工作 commit；归档 journal commit；统一 push。

## 完成证据
- [x] Canonical 位置日志、群名变化、旧/新安全段与 zero-insert queue 恢复。
- [x] 精确输入凭据、sqlite-vec 整次增量事务与 Builder/自动装配。
- [x] 增量/全量 oracle、失败/强停/并发/旧格式回归，正式 updater 工具链验证。
- [x] 确定性 3002 消息：360 → 7 次计算；真实 Qwen 152 消息：18 → 7 次计算。原始 JSON 在 research/。
- [x] 运维与可执行 spec 已更新；最终质量门禁结果见 validation.md。
- [x] 工作提交 43343ea；进入独立归档与 journal 收尾，完成后统一推送。
