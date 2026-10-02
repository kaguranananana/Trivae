# Archify 冻结 Plan 重放

用户已确认执行上轮建议的局部归因实验：dev-cite-archify 两份已保存且有效的 low/none Plan，各重放两次，共 4 次真实生产 Runtime。目的为初步区分 guidance 影响与同 guidance 下的输出方差，不证明长期质量等价。

边界：不新增 Planner 请求，不改生产 prompt、Runtime、Tools、Retrieval、Finalizer；不读取 Holdout/Calibration，不扩展 Case，不重试或替换失败。原始 16-run 实验与判断保持不变。所有本轮 attempts/HTTP/Trace/Answer/Evidence/评测完整保存。

验收：4 次 attempt 对齐真实 HTTP 与终端 Trace；实际首个请求除冻结 guidance 外字段相同；逐 run 人工核对 star 数值矛盾和前置消息引用关系；结果不足时明确不确定，不再追加付费运行。

已完成：4 runs、16 downstream HTTP、0 Planner HTTP，无 retry/timeout。原 none 两处错误未重现；相同 guidance 下观察到下游方差，low 出现 context 遗漏与日期关系错误。完整结果见 [report.md](experiment/report.md)。
