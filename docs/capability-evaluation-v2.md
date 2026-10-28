# Capability Suite v2：真实群聊评测

本套能力集按 [Anthropic 的 Agent 评测思路](https://www.anthropic.com/research/demystifying-evals-for-ai-agents)设计：保留能力边界题和独立回归集，联合使用确定性检查、模型辅助判断与人工核验，阅读 Trace 后再解释分数。原有能力集、回归集和历史实验均不覆盖。

## 当前数据与状态

`capability@v2` 有 30 个不同 Case：基础 4、中等 12、较难 14；覆盖跨群和时间比较、多人观点、条件检索、证据不足与冲突。来源覆盖 7 个群，参考消息时间从 2026 年 6 月至 10 月；近期技术讨论占比偏高，不代表全部群聊任务的自然分布。235 条 Case 内参考记录对应 205 条不同消息，交叉题可复用同一消息。

Suite 清单和不含群聊正文的目录见 `evaluation/suites/capability-v2.json`、`evaluation/capability-v2/catalog.json`。题目、各题语义要求、原文和消息 ID 保存在 Git 忽略的本机 `data/evaluation/capability-v2-20261028/`：

- `cases/`：版本化 Case，含非穷尽 Findings、引用和每题评分要求；`suite.json` 是同一 Suite 的本地副本。
- `evidence.json`：原文、时间、消息身份、转发关系和检索摘录；`review-queue.md` 提供逐题人工抽查视图，展示的摘录可能被截断。
- `evidence-conflicts.json`：8 个已发现的条件差异、表面冲突或因果不确定性，均待人工复核；没有列出不代表其他题不存在冲突。
- `evidence-audit.json`：30 题、235 条 Case 内参考记录的回读结果；仅证明 ID、群、时间、范围、原文和所存摘录一致，不证明语义推断或枚举完整。

线索来自原始消息检索及历史日报中值得追问的话题；后者只用于发现话题，参考摘录重新对当前冻结库逐条比对。语义与冲突归因由助手暂定，全部 30 题 `review:pending`，参考来源均 `adjudicated=false`。候选题不作为人工确认的 Ground Truth；遗漏未被收集的信息不等于不存在。`cap2-quota-timeline` 在完整 Suite 中为 v2，补充了可回读的转发子消息；试运行保留原 v1 和原运行事实。

冻结主库为 `data/evaluation/frozen-20261028-validated/`，与本轮开始时的真实库同为 864,615 条消息、Canonical/词法/语义 revision 98835；本轮使用独立工作副本 `data/evaluation/capability-v2-20261028-work/`。主库、工作副本、题目、原文、回答、Trace 和凭据都不提交。迁移实验需通过用户信任的私有方式连同完整冻结目录和本机评测目录一起保存；Git 中的目录清单不能代替私有 Case/数据。

## 评分约定

每题的 `reference_findings` 提供具体事实和边界；非穷尽参考消息仅作发现目标，不强制使用指定消息 ID 或参考措辞。等价且有支持的其他消息、合理表达及不同检索路径均应接受。

| 维度 | 判断 | 待审或不适用 |
| --- | --- | --- |
| Task Completion | 回答是否完成问题中的主要任务和限制 | 无完整回答时不评答案质量，单独记录运行失败 |
| Factual Correctness | 关键事实、人物、时间和关系是否有依据，是否正确归因 | 转述不能自动视为外部事实；证据不足时标未知或混合 |
| Evidence Recall | 已确认必要事实是否被充分覆盖 | 参考非穷尽时仅针对已确认目标；ID 命中是诊断，不是语义覆盖结论 |
| Citation Faithfulness | 每项实际结论是否被所绑定引用支持 | 引用存在不等于支持；证据不足和部分支持保留待审 |
| Unsupported Claims | `pass` 表示未发现无依据断言，`fail` 表示发现明确无依据断言 | 信息不足时不能简单把未知定为错误 |
| Cost / Latency | 记录实际 Provider 返回的 Token、运行耗时和工具调用 | 部分响应无 Usage 时只报已知下界；没有价格或账单时货币成本为未知 |

`capability_audit.py` 不创建第二套 Runner 或 Judge。它复用现有 Case、Evaluation Store 与 `run_report`，单独验证私人证据包，并把人工确认和模型辅助判断分开计数。正式维度分母只接受已有 `review:confirmed`、关键 Finding 及其 Evidence 已人工裁决、且有不需进一步裁决的人工答案 Review 的完整回答；非关键参考不强制全部确认。报告只汇总单一 Variant 和匹配 Case 评分版本的 Review，重复运行按 Run 计数。`mixed`、`unknown` 和未审核不进入 pass/fail 分母。模型辅助 Review 始终单列为暂定，不能冒充人工评审。当前 Codex 会话的试运行初审属于模型辅助 Review；尚未建立 Judge 与人工的符合率，也没有独立批量 Judge 对 v2 运行评分。

## 真实试运行（2026-10-28，待继续）

初始三题真实运行均失败：第一题在两次模型请求、两次工具调用后因 Provider `ConnectError` 终止；另两题在进入有效作答前同类失败。不是答案质量失败。首题已知输入 29,293、输出 80 Token，有一次响应的 Usage 缺失，不能把它作为完整总量。网络探测后单题恢复运行完成，耗时 160.641 秒、3 次工具调用，Runtime 返回 100,442 输入／1,702 输出 Token、4 次请求；货币成本未返回。两组是不同 Suite 的诊断运行，不是完整 v2 Baseline 或可直接比较的同集实验。

恢复回答的助手初审：任务完成 1/1、参考事实覆盖 1/1；事实正确、引用忠实、无依据断言各有 1 条 `mixed`，不计入 pass/fail 分母。主要疑点为旧图片消息与话题的关联未能仅凭引用确认，以及总结中一项额度体验未绑定直接支持消息；这些均需人工复核。所有正式质量指标的分母是 0，当前不能报正式准确率，也不能据此宣称 Agent 能力提升。

修订转发证据后的三题复测 3/3 完成、确定性检查 3/3 无失败；耗时合计 384.596 秒，13 次工具调用，Runtime 返回输入 362,129／输出 5,460 Token、12 次请求。助手暂定评审的任务完成及参考事实覆盖均为 3/3；事实正确、引用忠实和无依据断言各为 2/2 `pass`、另有 1 条 `mixed`，人工分母仍为 0。跨群题只命中 2/4 预设消息 ID，但找到可直接支持结论的转发子消息；不应把此 ID 命中数当作语义证据召回失败。第一题总结引用问题连续两次出现，仍需人工复核。此试运行使用独立校准 Suite，不冒充 30 题完整结果。

## 30 题 Baseline：中断后的真实结果

全套实验实际启动 13/30 题，10 条完整回答、3 条运行失败，17 题没有启动。三条失败分别为 1 次响应流提前断开和 2 次 Provider 明确返回 `subscription_sharing_usage_limit_exceeded`；第二次发生在 Router 阶段，异常向上暴露，实验随即停止。用量上限的重置时间未由该响应提供，不能从其他用量窗口推断。原失败和已保存 Run 不覆盖，整个实验状态为 `failed`，不是完成的全套 Baseline。

对 10 条完整回答的助手暂定 Review：

| 质量轴 | 暂定 pass / 已判 pass 或 fail | 其他 | 人工确认分母 |
| --- | --- | --- | --- |
| Task Completion | 7/8 | 2 mixed | 0 |
| Factual Correctness | 10/10 | 0 | 0 |
| Evidence Recall | 7/8 | 1 mixed、1 unknown | 0 |
| Citation Faithfulness | 9/9 | 1 mixed | 0 |
| Unsupported Claims | 10/10 | 0；pass 表示未发现无依据断言 | 0 |

这些数值只覆盖有回答的 10 次运行，来自本次 Codex 助手初审，所有 Case 与 Review 仍待人工核验；`mixed` 和 `unknown` 不计入 pass/fail 分母。三条系统失败单独计数，不伪装成质量失败。13 条运行的 Runtime 已知输入 Token **至少** 1,025,705、输出 **至少** 14,843，已知请求至少 40 次；两次响应没有 Usage、另有一次运行无 Usage，因此不是完整账单。13 条 Trace 耗时合计 1,074.976 秒；工具调用已知 44 次，覆盖 12/13 条，另一条未知。货币成本不可得。

再加上前述三组试运行，已知 Runtime 输入至少 1,517,569 Token、输出至少 22,085 Token、请求至少 58 次；仍有缺失 Usage，Router/其他阶段以及本次 Codex 会话中的取证与辅助评审也没有合并的完整成本记录。不要把这些下界解释为总账单。

最值得复核的现象：`cap2-harness-bridge` 未找到两条直接回答问题的消息，三次原始词法查询在同快照重放也未返回它们，原 Trace 的计数和前部一致，但原结果投影有截断，归因为 `likely:retrieval`；`cap2-student-terms` 的总结段引用遗漏直接支持消息，列为 `likely:citation`；`cap2-visualization` 遗漏同一发言者紧随回复的 HTML 提示，但 Trace 投影不完整，不能区分检索、上下文或生成选择；`cap2-video-workflow` 的问题没有指明日期或作品，Agent 找到另一段有依据的相似讨论，列为题目歧义待裁决。重放记录和逐题答案、引用、初审在本机 `harness-bridge-retrieval-replay.json`、`full-review-input/` 和 Evaluation Store 中。

实际 Run、确定性 Feedback、失败 Trace 和模型辅助 Feedback 已以 metadata-only 上传；逐题入口（需对应 LangSmith 工作区）：[30 题数据集与部分 Baseline](https://smith.langchain.com/o/4b9f5259-77e7-449b-9cb5-5da340ab4792/datasets/0ea1cbb6-6497-44b7-84bd-f17f586fc94c)、[初始三题试运行](https://smith.langchain.com/o/4b9f5259-77e7-449b-9cb5-5da340ab4792/datasets/d275acdf-a256-4f76-93e6-bc55c4831251)、[单题恢复与暂定 Review](https://smith.langchain.com/o/4b9f5259-77e7-449b-9cb5-5da340ab4792/datasets/5b4d0556-f213-4155-a1bd-d9ca911522f0)、[修订后三题复测](https://smith.langchain.com/o/4b9f5259-77e7-449b-9cb5-5da340ab4792/datasets/93256cf3-c495-48ac-9ddb-e263cc589afb)。部分 Baseline 的 13/13 Run、Trace 事件数量和 50 项暂定 Feedback 已通过 API 回读；其余 17 个 Example 仅登记 Case 身份，不包含虚构 Run，已核对与本机同步账本的对应关系。修订三题的 3/3 Run 与 15 项 Feedback 也通过 API 回读。为避免泄露私人消息，平台只含 Case ID、运行状态、结构化 Trace 元数据及 Feedback；原题、参考和回答在本机查看。页面未进行视觉验收。

## 新增题目、核验和运行

1. 在私人目录从原始消息独立收集事实、时间、群、消息 ID 和原文；记录话题线索、检索方法、冲突与不确定性。新增独立 Case 身份；修订已发布题目用现有 `trivae eval cases new-version`，不要覆盖旧版本。候选参考默认 `partial` 和 `adjudicated=false`，并以 `review:pending` 标记。
2. 在私人 evidence packet 中按 Case ID 和版本保存完整原文、`session_id`、毫秒时间、`sender_user_id`、摘录；转发消息另存 root、parent、path 和原始时间。Case 中每条 `internal_message_id` 必须与 packet 对应，packet 记录 Snapshot 和 freeze ID。
3. 使用以下命令重新检查；脚本只核验来源与原文，语义关联和参考完整性仍须人工审查。

```bash
trivae eval cases validate data/evaluation/capability-v2-20261028/cases
python scripts/audit_capability.py verify \
  --suite evaluation/suites/capability-v2.json \
  --cases-dir data/evaluation/capability-v2-20261028/cases \
  --packet data/evaluation/capability-v2-20261028/evidence.json \
  --freeze-manifest data/evaluation/frozen-20261028-validated/freeze.json \
  --database data/evaluation/frozen-20261028-validated/trivae.sqlite3
```

4. 人工确实检查后另存新 Case 版本，写明审核者、方法和限制；只有实际审核过的 Finding/Evidence 才能标 `adjudicated=true`，整题确认后用 `review:confirmed`。建立新 Suite 版本引用新 Case，保留旧版。不要把模型生成答案直接标成人工确认。
5. 从冻结主库创建新的工作副本，使用干净代码状态、与实际 Provider/模型匹配的新 Variant、独立 Evaluation 数据库和实验目录。以下 `--judge-version none` 明确表示没有自动 Judge；模型辅助或人工答案评审需用现有 `trivae eval review` 保存独立 Review。

```bash
trivae eval clone-data --manifest data/evaluation/frozen-20261028-validated/freeze.json \
  --output-dir data/evaluation/capability-v2-next-work
trivae eval run --suite evaluation/suites/capability-v2.json \
  --cases-dir data/evaluation/capability-v2-20261028/cases \
  --variant data/evaluation/capability-v2-20261028/baseline-variant.json \
  --database data/evaluation/capability-v2-next-work/trivae.sqlite3 \
  --evaluation-database data/evaluation/capability-v2-next-runs.sqlite3 \
  --freeze-manifest data/evaluation/capability-v2-next-work/freeze.json \
  --record-dir data/evaluation/capability-v2-next-record --judge-version none
python scripts/audit_capability.py report --suite evaluation/suites/capability-v2.json \
  --cases-dir data/evaluation/capability-v2-20261028/cases \
  --database data/evaluation/capability-v2-next-runs.sqlite3
```

Variant 文件中的代码版本、模型、工具和索引必须匹配将要运行的环境；若代码或设置已改变，先创建新的 Variant 身份，不复用旧身份。按成本和失败原因选择少量独立重复，不把不同 Snapshot、Suite 或模型的实验当作同条件对比。`report` 中 Token 是可观测运行数据，质量的正式分母与待审结果分开。

6. 保存 Review 后显式同步；示例只上传元数据。若用户确需平台展示内容，先准备不含私人信息的 `--content`，逐项核对后再使用。保留独立 Experiment 名称和本地记录。

```bash
trivae eval langsmith-sync --suite evaluation/suites/capability-v2.json \
  --cases-dir data/evaluation/capability-v2-20261028/cases \
  --evaluation-database data/evaluation/capability-v2-next-runs.sqlite3 \
  --trace-database data/evaluation/capability-v2-next-work/trivae.sqlite3 \
  --manifest data/evaluation/capability-v2-next-record/experiment.json \
  --experiment capability-v2-next --require-complete --metadata-only
trivae eval langsmith-resolve --experiment capability-v2-next
```

### 额度恢复后补跑本轮未完成题目

当前 `remaining-case-identities.json` 精确列出 **20 个 Case 版本**：3 条已有失败运行和 17 条未启动题，不包括 10 条已有完整回答的题。提供方额度恢复后，可在独立实验中使用 `--case-list` 只运行这些 Case；Runner 仍记录原 `capability@v2` Suite 身份，manifest 和 LangSmith Experiment 会记录本次选择，不修改旧的失败实验。下列命令需要先按当前干净 Git 版本和实际模型设置建立新的 `continuation-variant.json`；仓库或配置后来变化时应重新建立 Variant。

```bash
trivae eval clone-data --manifest data/evaluation/frozen-20261028-validated/freeze.json \
  --output-dir data/evaluation/capability-v2-continuation-work
trivae eval run --suite evaluation/suites/capability-v2.json \
  --case-list data/evaluation/capability-v2-20261028/remaining-case-identities.json \
  --cases-dir data/evaluation/capability-v2-20261028/cases \
  --variant data/evaluation/capability-v2-20261028/continuation-variant.json \
  --database data/evaluation/capability-v2-continuation-work/trivae.sqlite3 \
  --evaluation-database data/evaluation/capability-v2-continuation-runs.sqlite3 \
  --freeze-manifest data/evaluation/capability-v2-continuation-work/freeze.json \
  --record-dir data/evaluation/capability-v2-continuation-record --judge-version none
trivae eval langsmith-sync --suite evaluation/suites/capability-v2.json \
  --cases-dir data/evaluation/capability-v2-20261028/cases \
  --evaluation-database data/evaluation/capability-v2-continuation-runs.sqlite3 \
  --trace-database data/evaluation/capability-v2-continuation-work/trivae.sqlite3 \
  --manifest data/evaluation/capability-v2-continuation-record/experiment.json \
  --experiment capability-v2-continuation --require-complete --metadata-only
```

续跑入口和选择记录已在测试中验证；本轮因额度限制没有进行真实续跑。原实验和续跑是独立 Experiment，比较前要核对 Snapshot、Case、模型、配置、评分版本及代码变化；不可把旧的三条失败删掉或把两批不同运行称作一次完整原实验。

模型或网络失败应保留并按 Trace 分类；不要用模拟运行代替真实结果。已有平台同步、人工 Review 追加、时间语义与实验对比规则见 `docs/evaluation-langsmith.md`。
