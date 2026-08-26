# Implementation Plan

## Phase 1 — Regression tests first

1. 新增 budget 常量与 contract 测试，先证明当前统一 100 的行为不满足：
   - lexical 默认 1000、hard cap 5000；
   - semantic 默认 10、hard cap 20；
   - `dense_top_k=40` 独立；
   - SQL/member/structured 仍为 100。
2. 构造 150/300 条 FTS 命中，验证默认 broad lexical 不在 100 截断，超 hard cap 被 schema 和 Capability 分别拒绝。
3. 新增 context expansion 测试：100 direct hits + before2/after2 时 direct hits 全部保留；无剩余容量时不读取邻居；有容量时最多扩展 20 个来源。
4. 新增长消息 projection 测试：canonical candidate 可大于 100，model projection <=16k，显式 `truncated` 与 omitted hit count 可观察，visible handles 与 payload 一致。
5. 新增 Prompt contract fixture，验证 partial/truncated、mention/recommendation、intent/use、review/personal usage、hit/entity 的规则存在。
6. 新增 Evaluation axes/failure-label contract 测试。
7. 运行这些测试并保存预期失败，确认失败来自实现而非 fixture。

## Phase 2 — Minimal implementation

1. 在 limits 配置中定义 lexical、semantic、context source、expanded message、structured transport 与 Tool Result token 的独立常量，删除统一 alias。
2. 更新 typed inputs/query defaults，并保持 semantic `dense_top_k` 逻辑。
3. 更新 ExecutionScope 默认 umbrella ceiling；逐个 Capability 增加 tool-specific cap enforcement。
4. 更新 OpenAI provider schemas：lexical/semantic/SQL/member 分别使用正确 default/maximum。
5. 更新 ContextExpander 的 direct-hit-first 与 bounded source policy，并补充中文关键逻辑注释。
6. 拆分 canonical message/structured transport 容量。
7. 更新 model projection 的确定性裁剪与 omitted metadata，扩展 Trace 记录。
8. 更新通用回答 Prompt、Evaluation 默认 axes 与 Failure Label 词表。

## Phase 3 — Automated verification

1. 先跑新增定向测试。
2. 跑 retrieval/capability/evidence/runtime/evaluation 相关测试。
3. 跑全量 unit/integration suite、lint/type check（以仓库已有命令为准）。
4. 失败时复现、定位实现根因并最小修复；不改测试迁就错误实现。

## Phase 4 — Real archive benchmark

对真实 SQLite archive 分别记录 lexical 100/300/1000：

- DB query duration；
- context expansion duration；
- evidence building duration；
- model projection serialization duration；
- estimated tool tokens；
- Trace size。

另保留 context 2/2 的受控样本，用于确认 bounded expansion 消除了随 direct hits 线性增长的无收益查询。

## Phase 5 — Four real answer runs

按 Case A → B → C → D 的原始 wording 执行，逐条保存：

- Trace ID、tool sequence、tool calls、tool rounds；
- lexical total/returned/truncated；
- semantic hits/returned/dense_top_k/partial/truncated/coverage；
- Tool Result estimated tokens/truncated/omitted；
- final input/output tokens、citations、unresolved citations；
- 七个质量维度的人工/LLM review 和 Failure Labels。

对照 Before 表判断：

- A：recall 与类别区分是否改善；
- B：指定 joye URL 是否出现，是否避免错误否定；
- C：是否避免 intent/review → personal actual use；
- D：positive control 是否保持、无 URL 项是否列出、日期是否可读。

## Phase 6 — Failure classification and docs

1. 把未解决问题分为 Retrieval Coverage Failure 与 Claim Grounding Failure。
2. 若 retrieval 已足而 entailment 仍错，仅记录 Failure Case，不扩展本任务。
3. 完成 `validation.md`、`research/failure-case.md`、Before/After 表。
4. 更新 `interview-defense.md`，沉淀 budget 解耦和“citation unresolved=0 不等于事实正确”的设计解释。
5. 更新 PRD acceptance 状态和 Trellis check 记录。

## Phase 7 — Branch and commit

1. 获得规划批准后创建 `codex/retrieval-budget-quality-regression`。
2. 确认 diff 只包含本任务文件且无用户未授权改动。
3. 提交全部代码、测试与文档。
4. 记录 branch、commit、clean working tree；不合并到 `main`。
