# 本轮复现与恢复边界

以下是已执行命令；第一次执行代码为 d093512，成功创建唯一 a-smoke 目录，exit1。不能覆盖该目录或删除总 ledger。它包含一条真实失败，并非可复用质量 Baseline。

```bash
TRIVAE_MODEL_PROVIDER=chatgpt-plan \
TRIVAE_MODEL_NAME=gpt-6.1-sol \
TRIVAE_CHATGPT_REASONING_EFFORT=high HF_HUB_OFFLINE=1 \
uv run --all-extras python scripts/run_prompt_screening.py \
  --mode freeze-baseline \
  --case evaluation/cases/benchmark/dev/dev-lexical-chatlog-alpha.json \
  --case evaluation/cases/benchmark/dev/dev-para-ts-learning.json \
  --case evaluation/cases/benchmark/dev/dev-context-mattpocock-1.json \
  --case evaluation/cases/benchmark/dev/dev-zero-empty-1.json \
  --database .trellis/tasks/10-05-prompt-policy-audit/experiment/snapshot/trivae.sqlite3 \
  --semantic-index .trellis/tasks/10-05-prompt-policy-audit/experiment/snapshot/trivae.semantic.sqlite3 \
  --output data/evaluation/gpt-high-ablation-20261018/a-smoke \
  --max-provider-calls 16 \
  --provider-budget-ledger data/evaluation/gpt-high-ablation-20261018/total-budget.json \
  --total-max-provider-calls 120
```

进程环境覆盖 `.env`，没有写用户设置；HF_HUB_OFFLINE 固定两侧相同本地缓存条件，不是检索 fallback。本轮尚未到达 embedding。

当前停止，不执行新的推理复现。恢复前先解决 report.md 的两项条件，并使用新 output 名称、原总ledger、固定 high，不扩大120。真实账号目录由 `uv run --all-extras trivae auth models --provider chatgpt` 只读确认。Prompt 身份通过提交、全文原件与精确相等校验复核，不新增摘要算法。

离线验证：

```bash
uv run --all-extras python scripts/run_prompt_screening.py --mode static
uv run --all-extras pytest -q
```

真实原件中的 failed frozen_baseline 标签是原脚本已产生的失败事实，收尾不回填修改；当前脚本会标记 failed_baseline，复用检查也明确拒绝旧失败记录。旧 DeepSeek baseline 仅历史参考，不能放入本轮 candidate-only。
