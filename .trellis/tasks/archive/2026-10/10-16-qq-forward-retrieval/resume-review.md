# 显式 semantic 续建与自然问法核验审阅

## 范围与边界

本次只审阅长跑实际中断后追加的 `resume` 路径，以及真实核验脚本的自然问法成功判定。依据 `design.md` 的中断/续建段、`prd.md`、`implement.md`、`check.jsonl`、backend quality/database/forwarded-message/error-handling 规范。原完整转发功能已有独立审阅，本次不重新声明全部功能验证完成。

未修改生产代码、分块/解析规则、真实库、正在运行的构建进程、原始 QCE 文件或冻结 Evaluation；未 commit/push。只有本审阅记录由 reviewer 写入。

## Findings (fixed)

无；按本次 review ownership，只报告具体问题，交由主会话修改其拥有的脚本。

## Findings (not fixed)

### P2：核验脚本把未绑定到回答正文的 Evidence 误计为已引用

- 文件：`verify_forward_retrieval.py`，审阅时第 121–135 行。
- 问题：脚本遍历所有 `answer_artifact.evidence_items`，发现 expected child 并成功回读 Canonical 后即写入 `cited_children`。它没有检查对应 `evidence_id` 是否出现在 `citation_bindings` 中，因此不能证明答案正文引用了该子消息。
- 已复现：使用现有 `_child` / `_envelope` / `_record` 测试 fixture，构造 `e1` 引用匹配子消息、`e2` 引用普通消息、正文 `b1` 仅绑定 `e2`。经过生产 `validate_answer_artifact` 严格校验后，现脚本等价筛选仍得到 `['e1']`，实际已绑定的子消息 Evidence 为空。
- 复现输出：`{'strict_validation': 'passed', 'script_cited_evidence': ['e1'], 'answer_bound_evidence': ['e2'], 'actual_bound_child_evidence': []}`。
- 最小建议：在脚本内根据 `citation_bindings` 收集已绑定的 Evidence ID，只将这些 Evidence 的匹配子消息计为引用，并在 report 保留 block/evidence 绑定用于复核。无需改变现有 Evidence Contract。
- 未修复原因：该脚本归主会话 ownership；具体复现已发回主会话。此问题影响核验结论的严谨性，不是已确认的生产检索缺陷。

## 已核对的续建事实

- `builder.rebuild(*, resume=False)` → `Application.rebuild_semantic_index(*, resume=False)` → CLI `semantic rebuild --resume` 透传一致；默认仍执行 `start_rebuild`，不自动续建或重试。
- `begin_resume` 在模型加载前核对完整 identity、Canonical revision/count、forwarded count；missing/completed/stale 明确拒绝，拒绝身份/水位漂移时不修改原 rows/state。
- 已存 metadata/vector 通过计数、missing、orphan 检查一一对应。首次计算前失败且无 vec 表的零块状态被正确接受。
- 块写入与进度是两个事务，强停可留下已提交块领先 state chunk count 的合法窗口。实现接受该窗口，以相同确定性双流重放全部 Parent/Child，避免按滞后进度跳过未完成 Parent。
- 每批复用前逐字段匹配所有持久 chunk metadata，并确认向量存在；仅对 missing chunks 调用模型/插入。`embedding_count` / batch count 统计本次实际计算，`reused_chunk_count` 独立报告。
- 结束前核对 Canonical revision，并要求 `reused_chunk_count == begin_resume` 的实际已存块数；不能把重放未覆盖的旧块混入 completed 索引。普通和转发覆盖计数分别核对。
- 回归覆盖原生 Parent 中断、普通/转发 batch 交界、合法进度滞后、重开后与干净构建全部 metadata/vector 及检索事实等价、首次模型失败、partial、identity/revision/两类计数漂移、missing/completed 与四类损坏，以及 CLI 真实 facade 透传。

上述边界未发现新的实际缺陷；没有为假设状态增加防御、兼容或新测试。

## 自然问法核验边界

自然模式只改变实际 `application.query(QueryRequest(...))` 的用户文本，不指定工具或转发类型；scope 仍由可信 `ExecutionScope` 固定群聊。脚本保留真实 lexical/semantic 工具直连验证，Agent 自行选择至少一种成功检索工具；默认 `both` 模式仍要求模型实际执行两种工具。Agent 返回值、Trace 与来源回读均来自生产路径，没有复制检索或生成实现。上面的 citation binding 漏检须修正后再将自然问法运行报告记为“已引用具体子消息”。

本 reviewer 没有运行真实模型、切换索引或把进行中的全量构建计为完成；全量续建、校验、原子切换与两组真实 Agent 结果由主会话继续核验。

## Verification

| 命令 | 本次实际结果 |
| --- | --- |
| `uv run ruff check src tests scripts/verify_forward_retrieval.py` | pass |
| `uv run mypy src scripts/verify_forward_retrieval.py` | pass；123 files |
| `uv run pytest -q tests/test_semantic_resume.py tests/test_semantic_retrieval.py tests/test_forward_semantic.py` | pass；36 tests，3.07 s |
| `git diff --check` | pass |
| 未绑定 Evidence 的内存复现 | 复现上述脚本假阳性；不读写真实库 |

原完整 feature 的全仓检查与 worker 的 1046 项结果由主会话提供，本记录不冒充 reviewer 再执行过的结果。Web 未改动，本次不重复 Web 检查。

## 主会话修复复核项

上述 P2 已修复：脚本新增 `cited_message_sources()`，只从正文 `citation_bindings` 的 block → evidence → source 链提取来源，报告保存 block/evidence ID，并核对 Canonical 回读的父子位置及双时间。新增 `test_forward_verification.py` 复现未绑定子消息不算引用，并断言实际绑定后可计入；测试通过。主会话补跑全仓 1047 tests（30.04 s）、脚本 Ruff 与 src+脚本 Mypy 123 文件全部通过。已保存的两项真实定向 Artifact 再次按实际 binding 核验，分别有 4 / 6 条正文 Citation 指向对应子消息；没有覆盖先前运行文件。
