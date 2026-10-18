# 设计边界与七问

1. Responsibility：Responses wire事件归现有Model适配；Runtime/Runner/工具/Finalizer不另建。索引通过现有builder生成独立派生数据库。
2. Failure Cases：SDK无metadata事件、原始事件未捕获、字段误解、伪终态、未知扩展、索引stale、预算耗尽、语义合成退化。
3. Observability：先用原Trace/请求定位，若需有界再现则用同ledger捕获安全事件形状/metadata，隐藏正文不公开。真实查询保留原Evaluation/Trace。
4. Attribution：wire schema不匹配属于Provider adapter；检索覆盖/最终答案独立裁决。
5. Decision：对比官方协议、本地/可用新版SDK；仅在证据确定后选升级或显式typed扩展，不泛化忽略未知事件。协议核心终态继续强校验。
6. Verification：原failure复现红灯、typed扩展合法/非法/未知/断流/失败/工具多轮/Usage回归、静态、真实High、A/B/C同条件。
7. Regression：固定真实metadata形状的脱敏fixture，冻结模型/工具/索引/快照身份，不修改GT。

预计代码边界：chatgpt_responses.py和对应测试；必要时依赖版本；实验脚本仅阻塞正确性修复；prompt.py仅最终质量门禁完整通过才修改。索引准备独立于协议，可委派但不得在子Agent发送GPT请求。公开结论由主Agent整合。
