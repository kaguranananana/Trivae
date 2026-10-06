# 低成本 Prompt Evaluation

入口：`uv run --all-extras python scripts/run_prompt_screening.py --help`。默认真实调用上限0，任何 real mode 都必须显式指定正数。实验输出放在 ignored `data/evaluation/`；不提交私人聊天、Trace、请求或数据库。

| mode | 行为 | 成本 |
| --- | --- | --- |
| static | 不读.env/密钥、不构造Provider；Ruff/mypy/相关pytest | 0 |
| first-tool | 正式 Query/SDK 首轮完成后记录 tool/arguments，拦截所有工具执行；usage/latency 见同一Trace | 通常每case 1 request；硬上限需显式填写 |
| targeted | 根据现有 suite_tags 的 policy 选case，复用冻结Baseline | 只跑candidate，repeat=1 |
| candidate-only | 验证冻结原文和所有非Prompt条件再跑candidate一次，生成既有PairedComparison/ReviewPacket | 不重跑Baseline |
| freeze-baseline | 一次性冻结当前生产Prompt结果；之后复用 | 显式付费，不是日常默认 |
| full-gate | fresh baseline+candidate；显式AB或BA；人工语义审查仍必需 | 仅release阶段 |

所有 real mode 都要指定实际已绑定 snapshot 的 `--case`（可重复）；不接受自动整套 suite。`targeted` 要 `--policy` 和 `--baseline-dir`，没有匹配case显式报错。`full-gate` 不自动执行整个suite/ABBA/repeat=3；需要反序时另起新输出目录执行BA，并共享本轮预先预算。当前standard路由固定，不调用Planner。

示例（路径由实际冻结case替换，不能拿 unavailable seed 假装真实snapshot）：

```bash
uv run --all-extras python scripts/run_prompt_screening.py --mode static
uv run --all-extras python scripts/run_prompt_screening.py --mode first-tool --case data/evaluation/cases/reply.json --candidate-prompt data/evaluation/prompt.txt --database data/evaluation/snapshot/trivae.sqlite3 --output data/evaluation/probe-reply --max-provider-calls 1
uv run --all-extras python scripts/run_prompt_screening.py --mode candidate-only --case data/evaluation/cases/reply.json --candidate-prompt data/evaluation/prompt.txt --baseline-dir data/evaluation/baselines --database data/evaluation/snapshot/trivae.sqlite3 --output data/evaluation/candidate-reply --max-provider-calls 4
```

`--repeat`仅接受1。怀疑单case Provider randomness 时指定先前candidate artifact、明确review与reason：`--repeat-on-failure <artifact> --review borderline --repeat-reason provider_randomness --candidate-extra 2`。原Prompt/条件改变则拒绝追加。`--review regression`直接淘汰，0调用，不因收集数据继续跑。真实语义审查不能靠 completed/finalizer 自动决定；明显工程失败则自动停止后续case。实验发生的所有请求数保存在provider-ledger，货币cost不可靠时记录null。

人工复核comparison与完整Trace：tool selection/order/arguments/repeated retrieval/expansion/stopping；GT送达/anchor/reply/projection omission；事实/作者/UTC/时间关系/reply/recommendation/inventory；单列强负面与其证据边界；最后才看token、tool rounds、result size、latency。comparison的pending_review不是Accepted。

当前历史实验脚本 `real_pair.py` 保留完整原始结果，不再作为日常默认入口；不得继续使用旧失败candidate作为baseline。L0/L1失败停止该候选；本轮没有真实Provider执行，也没有额外fresh Baseline成本。

## 零API导入既有生产结果

`freeze_recorded_prompt_baseline.py`显式读取旧`real_pair`的baseline cell，核对生产原文、query、route与settings，并复用同一冻结snapshot。不是隐式兼容或重新执行Agent；旧candidate被拒绝。没有人工GT则保持空标注，不捏造checks，完整Trace/答案/证据保留供Development人工review。

```bash
uv run --all-extras python scripts/freeze_recorded_prompt_baseline.py --cell .trellis/tasks/10-05-prompt-policy-audit/experiment/baseline-discussion-3 --snapshot .trellis/tasks/10-05-prompt-policy-audit/experiment/snapshot/trivae.sqlite3 --baseline-commit 460259d --policy discussion --policy negative --policy retrieval --output data/evaluation/prompt-frozen-20261006
```

本轮已本地冻结6个历史场景：discussion/reply/github/fact/empty/recent；每个保存原prompt+commit、snapshot、query、完整scope、provider/model、预算、Tool Schema、完整记录请求、Trace、证据、答案、既有Evaluation snapshot、usage与latency。以原大改失败中相关的最终baseline记录为固定Development参考，不合并重复、不计新运行、不宣称新质量统计。6/6生产SDK原始schema/model_settings/snapshot reuse预检通过；0网络请求、未执行Candidate。

本地case与baseline目录：`data/evaluation/prompt-frozen-20261006/cases/`和`baselines/`。实际聊天材料只在ignored目录；版本库只存导入器、说明与不含聊天正文的测试。Snapshot/模型配置/工具契约漂移时必须拒绝复用，不能偷换当前默认值。
