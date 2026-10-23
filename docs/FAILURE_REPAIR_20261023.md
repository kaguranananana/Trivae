# 剩余 Failure Case 修复与验收

2026-10-23。对应 [FAILURE_AUDIT_20261023.md](FAILURE_AUDIT_20261023.md) 的后续修复；工程实现及真实运行冻结版本为 `f9fc1dc`。

五项工程缺口已经修复。原笔试题两次独立查询均找到直接经历，Nanobot、Matt、Archify 及 owner 控制题也完成当前配置复验；这批答案未发现旧的结论—引用错配。没有因此新增固定关键词规则、语义裁判、自动重试或宽松 JSON 解析。

## 工程修复

| 问题 | 根因与修改 | 实际验收 |
| --- | --- | --- |
| 完整转发后导入仍被判 equal duplicate | 稳定根字段之外，复用正式转发树比较 occurrence 的正文和身份；只吸收保留全部已知事实的单调补齐，旧 Canonical raw 保存为 `superseded_forward` | 根层、嵌套、幂等、较旧空导出及已知正文冲突；同文件自动导入后 FTS 与语义索引均发布，补齐正文可检索 |
| 5 秒 SQL 拖住异步服务 | SQL 计算进入工作线程，其连接在该线程创建/关闭；Trace 的开始、完成和错误仍由原调用线程记录 | SDK 真实四表交叉 SQL 在 5.0005 秒显式超时，20ms 回调在 21.0ms 执行，额外迟到约 1.0ms；ASGI 回归中 SQL 尚未结束时 readiness 与 Stop 均返回，流终态为 aborted |
| 多词 AND 夹单汉字漏召回 | 常规词仍走原 FTS/BM25；单汉字项在既有 Han 索引求交，多项单汉字同样执行 AND | 普通及转发消息的混合词、多个单字、群与时间范围回归通过；当前 `github.com 荐` 为 35 命中，其中包含转发，对照原生主表字面同时命中 20 条 |
| 部分覆盖零命中只能失败或降级 | 新增正式 `kind=insufficient_evidence`；资格由同一 Host 事实判断并告知模型，Finalizer 直接编译为 valid Artifact | 真实 partial 空检索 valid；完整 `no_result` 在同历史下仍 failed；有候选、工具错误或未检索不能冒用；Application→SDK→会话保存通过 |
| 流式坏 JSON 无法定位 | 解析异常附加 Unicode 字符偏移、chunk 序号、坏字符、前 128/后 64 字符和最多四层容器状态；失败终态前保存 `answer.parse.failed` | 跨 chunk 非法转义精确定位与 SQLite Trace 持久化通过；非法输出仍失败，不补写、修复或重试 |

导入新增 `enriched_count`，与新增、重复和冲突分开计数；已有数据库自动添加该批次字段。实际正文 UPDATE 推进原 Canonical revision，复用既有索引队列，不新增第二套同步机制。只替换完整 incoming，不拼接两个互补且各自缺事实的树；已知正文或身份冲突保留为 conflict。

SQL 的 Stop 验收证明服务能及时处理取消；工作线程中的 SQLite 计算仍由原 5 秒期限约束，没有声称 Stop 已即时终止底层计算。保留原同步 ToolHandler 接口：正式 SQL 提供显式异步方法，既有同步注册 handler 保持原线程调用。首次全量回归发现五个合法同步 handler 被误拒，修正接口实现后原测试断言通过。

## 当前模型真实复验

只冻结一份 Canonical/语义索引：834,636 条消息、revision 68,856，索引 completed 且一致。使用现有 Plan / gpt-6.1-sol / medium、6 工具轮、8 回合、200,000 总证据池、128,000 单次上限，强制 Standard 路径、全部会话与 trusted max_results=5,000。运行中没有修改源码、Prompt、HEAD、模型配置或冻结输入。

| 独立样本 | HTTP / 工具轮 | Finalizer | Canonical 引用回读 | 结论 |
| --- | --- | --- | --- | --- |
| 原笔试题，第 1 次 | 3 / 2 | valid | 2 / 2 | semantic 后自行 lexical `构造`、limit=5000；已知目标进入材料，引用同文直接经历，区分设想与最终效果 |
| Nanobot | 3 / 2 | valid | 5 / 5 | 归属、功能、团队共享后续计划分别受本段来源支持，计划没有写成已完成 |
| Matt | 3 / 2 | valid | 26 / 26 | 短评的实际 reply target 确为目标仓库；保留正反反馈，并区分机器人安装说明和真人体验 |
| Archify | 4 / 3 | valid | 35 / 35 | 概述直接绑定实际使用、细节缩减、耗时与额度来源；没有把输入方式回复当成保真问题已解决 |
| owner 控制题 | 3 / 2 | valid | 13 / 13 | 直接观点、重要业务边界和另一实习生抱怨分别引用，不强行合并为同一案例 |
| 部分覆盖空结果 | 2 / 1 | valid | 无消息引用 | 自主输出 insufficient_evidence，保留未展开转发与 partial 限制，不宣称全范围为空 |
| 原笔试题，第 2 次 | 3 / 2 | valid | 1 / 1 | 再次取得目标并引用直接经历，未编造最终方案或笔试结果 |

总共 21 次实际模型请求，账本与 Usage 均为 21；输入 500,317、输出 6,318、合计 506,635 Token，其中 cached input 38,656。没有 Judge、隐式补跑、产品重试、索引重建或重复复制每题数据库。82 处引用按正式 Canonical 接口核对了实际切片、偏移、作者、时间和群范围，转发同样逐 occurrence 回读；引用一致性与自然语言支持分别审阅。

本轮 Host 投影省略、hit 省略和投影截断均为 0，工具池最高约 51,842/200,000，未出现工具参数、执行或预算错误。检索工具自身的 top-K、coverage partial 和源正文缺口仍如实保留，不能将这些结果当作全历史穷尽。

这批真实样本没有复现旧的笔试遗漏和引用错配，因此没有继续叠加质量 Prompt 或机械语义校验。两次笔试与其余各一次只构成当前样本证据，不能给稳定成功率；与旧语料/预算也不是单变量 A/B。Nanobot 本次没有输出旧数值，不能据此声称一般数值绑定已获验证。逐段评审为 Assistant provisional，不升级为人工通过率。

## 回归与本地应用

- 完整后端：`uv run pytest -q` → **1280 passed / 1 skipped**（31.26 秒）。
- `uv run ruff check src tests scripts`、`uv run mypy src`（129 个源文件）、`git diff --check` 通过。
- 前端 **80 passed**，typecheck、lint、build 通过；新增取证不足的中文限制标签。
- 两个原红探针同时通过：`uv run python -m scripts.audit_failure_boundaries --output data/evaluation/failure-repair-20261023/offline-probes-final.json --require-responsive-sql --require-forward-enrichment`，exit 0、模型请求 0。
- 本地 Web 已正常重启加载修复及构建。readiness 数据库 ready、语义 completed，834,636/834,636、revision 68,856 对齐，Plan/Sol ready；页面 HTTP 200。未重算在线语义向量。

真实验证执行器为 [run_failure_repair_validation.py](../scripts/run_failure_repair_validation.py)。先 `prepare` 冻结一次输入及协议，再按已登记 unit `run`；已存在的运行目录不覆盖，失败工件保存后明确退出。原公开 Development 问题不更改 GT，也未读取封存 Holdout。

完整答案、Trace、请求账本、同一份快照、逐段 review packet 和 source checks 位于本地 ignored `data/evaluation/failure-repair-20261023/live/`；汇总为 `review-summary.json`。零模型探针及 Web readiness 保存在其上级目录。

## 仍然存在的边界

当前源数据仍有 245 个未展开转发节点。修复让以后确实拿到的完整版本进入 Canonical；没有凭预览恢复正文，也没有把 245 个节点都归因于原导入缺陷或声称全部补回。历史恢复仍需要真实更完整的导出。

旧 DeepSeek 流式解析失败的坏正文没有保存，无法追溯其具体坏字符；本轮修的是未来失败的定位能力，不能声称已重放并修复那份历史输出。一般语义改写召回、所有有用信息零遗漏、额外第 4–6 轮收益、Planner 的稳定收益，以及实体手机键盘/读屏仍是独立实验，不由本次工程回归或七次样本推导。
