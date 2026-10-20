"""从不可变实验产物计算公开报告，并保存私有失败与答案审核材料。"""
from __future__ import annotations

import json
import platform
import sqlite3
from pathlib import Path

from scripts.cjk_bigram_benchmark import ROOT, summarize, write_new
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository

PUBLIC = Path('evaluation/experiments/cjk-bigram-v1')


def percent(value: float) -> str:
    """统一显示百分数，底层 JSON 保留完整精度。"""
    return f'{value * 100:.3f}%'


def comparison(label: str, a: float, b: float, counts: str = '') -> str:
    """区分绝对百分点和相对百分比；零基线不计算相对值。"""
    relative = '不适用（A=0）' if a == 0 else f'{(b / a - 1) * 100:+.2f}%'
    return f'| {label} | {percent(a)} | {percent(b)} | {(b-a)*100:+.3f} pp | {relative} | {counts} |'


def category_changes(results: dict) -> str:
    """分类同时显示遗漏比例与两种增幅，避免让读者从箭头自行反推。"""
    lines = ['### 分类增幅与遗漏比例', '',
             '| 分类 | 漏召回比例 A→B | Recall@10 macro 绝对/相对 | Hit@10 绝对/相对 | MRR@10 绝对/相对 | 全深度micro 绝对/相对 |',
             '|---|---:|---:|---:|---:|---:|']
    for category in ('short', 'long', 'mixed', 'control', 'absent', 'single'):
        a, b = results['categories'][category]['A'], results['categories'][category]['B']
        denominator = a['completeness']['denominator']
        missing = '不适用' if not denominator else (
            f"{a['missing']/denominator*100:.3f}%→{b['missing']/denominator*100:.3f}%")
        differences = []
        for metric, field in (('recall_at_k','macro'), ('hit_at_k','macro'),
                              ('mrr_at_k','macro'), ('completeness','micro')):
            x, y = a[metric][field], b[metric][field]
            if x is None:
                differences.append('不适用')
            else:
                relative = '不适用（A=0）' if x == 0 else f'{(y/x-1)*100:+.2f}%'
                differences.append(f'{(y-x)*100:+.3f} pp / {relative}')
        lines.append('| ' + category + ' | ' + missing + ' | ' + ' | '.join(differences) + ' |')
    return '\n'.join(lines)


def main() -> None:
    """质量只用修正版 Oracle；性能使用无 Agent 并发的独立测量。"""
    root = ROOT / 'oracle-v2'
    results = json.loads((root / 'results.json').read_text())
    frozen = json.loads((root / 'frozen.json').read_text())
    old = json.loads((ROOT / 'frozen.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    timings = json.loads((root / 'latency-final.json').read_text())
    specs = {case['case_id']: case for case in frozen['cases']}
    corpus = sqlite3.connect(ROOT / 'documents.sqlite3')
    corpus.row_factory = sqlite3.Row
    canonical = SQLiteCanonicalReadRepository(ROOT / 'snapshot.sqlite3')
    failures = []
    for row in results['rows']:
        case = specs[row['case_id']]
        reference = set(case['reference_ids'])
        arms = {}
        for side in ('A', 'B'):
            returned = set(row[side]['all_ids'])
            false_ids, missing_ids = sorted(returned - reference), sorted(reference - returned)
            # 样例来自已经冻结的 corpus；完整身份集合用于逐条复现，而非只保存摘要。
            arms[side] = {'false_positive_ids': false_ids, 'missing_ids': missing_ids,
                          'examples': [dict(corpus.execute('SELECT * FROM documents WHERE internal_message_id=?',
                                                           (identity,)).fetchone())
                                       for identity in (false_ids[:2] + missing_ids[:2])]}
        failures.append({'case_id': case['case_id'], 'term': case['term'], 'scope': 'all 12 sessions',
                         'reference_ids': case['reference_ids'], 'strategies': arms})
    write_new(root / 'failure-cases.json', failures)
    revisions = [{'case_id': case['case_id'], 'term': case['term'], 'old': len(before['reference_ids']),
                  'new': len(case['reference_ids'])}
                 for before, case in zip(old['cases'], frozen['cases'], strict=True)
                 if before['reference_ids'] != case['reference_ids']]
    write_new(PUBLIC / 'oracle-correction.json', {'reason': 'LIKE stops at NUL; instr searches full text',
                                               'changed_reference_cases': revisions, 'query_changes': 0})
    write_new(PUBLIC / 'latency-final.json', timings)
    records = []
    for folder in ('agent', 'agent-continuation'):
        records.extend(json.loads((ROOT / folder / 'records.json').read_text()))
    agent_rows, packet = [], ['# Agent 答案与 Canonical 引用审核包\n\n状态：自动字面核对 + AI 诊断；未经人工审核。\n']
    for record in records:
        q = record['run']['query_result']
        ids = {identity for source in q['evidence_sources']['sources'] for identity in source['message_ids']}
        reference = set(specs[record['case_id']]['reference_ids'])
        direct = {hit['internal_message_id'] for call in q['retrieval_calls']['calls'] for hit in call['direct_hits']}
        # 只判定来源存在和完整字面串，不把它等同于所有句子的语义正确率。
        existing = {identity for identity in ids if canonical.read_message_by_id(identity) is not None}
        usage = q['runtime']['usage']
        agent_rows.append({'case_id': record['case_id'], 'term': specs[record['case_id']]['term'],
                           'strategy': record['strategy'], 'status': record['status'],
                           'direct_literal_hits': len(direct & reference), 'evidence_literal_hits': len(ids & reference),
                           'evidence_sources': len(ids), 'existing_sources': len(existing), 'usage': usage,
                           'latency_ms': record['latency_ms'], 'tools': q['runtime']['tool_behavior']['tool_sequence'],
                           'trace_completeness': record['run']['operational_measurements']['trace_completeness'],
                           'finalization_error': q['finalization_error'], 'human_verified': False})
        packet.append(f"\n## {record['case_id']} / {record['strategy']} / {record['status']}\n\n{q['answer_text']}\n")
        for identity in sorted(ids):
            message = canonical.read_message_by_id(identity)
            packet.append(f'\n### {identity}\n\n{message.normalized_content}\n')
    (ROOT / 'agent-review.md').write_text('\n'.join(packet), encoding='utf-8')
    # 首批 hook 未覆盖当前 SDK 的 httpx2，真实响应数从生产 Trace/Usage 核对。
    confirmed_requests = sum(row['usage']['requests'] for row in agent_rows) + 1
    tokens = {key: sum(row['usage'].get(key, 0) for row in agent_rows)
              for key in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens')}
    accounting = {'completed_record_requests': confirmed_requests - 1, 'interrupted_completed_requests': 1,
                  'confirmed_http_responses': confirmed_requests, 'possible_cancelled_inflight_requests': 1,
                  'http_attempt_range': [confirmed_requests, confirmed_requests + 1],
                  'remaining_batch_transport_requests': len(json.loads((ROOT/'agent-continuation/http.json').read_text())),
                  'tokens_completed_records': tokens,
                  'interrupted_confirmed_usage': {'input_tokens': 6048, 'output_tokens': 188, 'total_tokens': 6236},
                  'interrupted_inflight_usage': 'unknown; not fabricated',
                  'original_zero_counter_invalid': True, 'budget_upper_bound': 40}
    write_new(ROOT / 'agent-accounting-correction.json', accounting)
    write_new(PUBLIC / 'agent-summary.json', {'rows': agent_rows, 'accounting': accounting,
                                            'interrupted': {'case_id': 'cjk-45', 'strategy': 'A',
                                                            'cause': 'stopped to correct HTTP transport instrumentation'}})
    cjk = summarize([row for row in results['rows'] if row['category'] in ('short', 'long', 'mixed')])
    pure = summarize([row for row in results['rows'] if row['category'] in ('short', 'long')])
    overall = results['overall']
    header = '| 指标 | A unicode61 | B bigram v2 | 绝对提升 | 相对提升 | 实际分子/分母（A → B） |\n|---|---:|---:|---:|---:|---|'
    metrics = []
    for key, label in [('recall_at_k','Recall@10'),('hit_at_k','Hit@10'),('mrr_at_k','MRR@10'),('completeness','全深度字面覆盖')]:
        a, b = overall['A'][key], overall['B'][key]
        macro_counts = f"Σ比率 {a['macro']*57:.6f}/57 → {b['macro']*57:.6f}/57"
        metrics.append(comparison(label+' macro', a['macro'], b['macro'], macro_counts))
        if key in ('recall_at_k', 'completeness'):
            metrics.append(comparison(label+' micro', a['micro'], b['micro'],
                                      f"{a['numerator']}/{a['denominator']} → {b['numerator']}/{b['denominator']}"))
    classes = []
    for category in ('short','long','mixed','control','absent','single'):
        group = [row for row in results['rows'] if row['category'] == category]
        scores = results['categories'][category]
        n = sum(row['reference_count'] > 0 for row in group)
        def cell(side, key, field):
            value = scores[side][key][field]
            return '不适用' if value is None else percent(value)
        classes.append(f"| {category} | {len(group)}/{n} | {cell('A','recall_at_k','macro')} → {cell('B','recall_at_k','macro')} | "
                       f"{cell('A','hit_at_k','macro')} → {cell('B','hit_at_k','macro')} | "
                       f"{cell('A','mrr_at_k','macro')} → {cell('B','mrr_at_k','macro')} | "
                       f"{scores['A']['completeness']['numerator']}/{scores['A']['completeness']['denominator']} → "
                       f"{scores['B']['completeness']['numerator']}/{scores['B']['completeness']['denominator']} | "
                       f"{scores['A']['missing']} → {scores['B']['missing']} |")
    regressions = [row for row in results['rows'] if row['B']['top_true_positive'] < row['A']['top_true_positive']]
    agent_table = []
    for case_id in frozen['agent_case_ids']:
        cells = []
        for side in ('A', 'B'):
            row = next((row for row in agent_rows if row['case_id'] == case_id and row['strategy'] == side), None)
            cells.append('主动中断；不评分' if row is None else
                         f"{row['status']}; direct={row['direct_literal_hits']}; final={row['evidence_literal_hits']}/{row['evidence_sources']}; "
                         f"{row['usage']['requests']} calls / {row['usage']['total_tokens']} tokens / {row['latency_ms']/1000:.1f}s")
        agent_table.append(f"| {case_id} {specs[case_id]['term']} | {cells[0]} | {cells[1]} |")
    a_time, b_time = timings['summary']['A'], timings['summary']['B']
    build = results['build']
    report = f'''# Trivae CJK bigram v2 检索对照实验

执行日期：2026-10-20。结论：**大幅改善穷举字面覆盖，但前十排序并非全面改善，存在混排误匹配、单字缺失及性能开销；没有稳定 Agent 质量提升的证据。**

## 实验身份与审计

生产检索代码基于 `201a81b`。实验期间生产 tokenizer、索引算法、Agent Prompt 均未修改。唯一 `src` 改动为 Evaluation Snapshot 的结构化身份长度修复；冻结前复现并测试，提交身份见该目录关联的 Git 提交。执行时实验脚本位于工作树，随后提交，不能称为 clean-worktree execution。

- Snapshot：809,850 canonical + 13,985 forwarded occurrences = **823,835** indexed documents；12 sessions、80 sources、canonical revision 44070。时间范围 1753011800000–1792418450000 ms。仍有 217 个未展开转发节点；穷举只涵盖快照内可恢复正文。
- 环境：SQLite {manifest['sqlite']}，Python 3.12.13，{platform.platform()}。索引复制自同一只读备份，生产库未重建或写入。
- A：原文 FTS5 unicode61；B：现有 `normalize_lexical_index_text` 与查询同源函数。schema、行顺序、SQLite 配置、Scope、limit=10、BM25 和稳定 tie-break 一致。
- 查询用生产 `_lexical_match_union`，多空白 term 为 literal AND；每个归一化 term 为 quoted phrase。实验只替换 A 的 MATCH 文本，不改 Scope SQL。实验FTS的source_message_id为NULL（UNINDEXED）；该列不参与匹配或BM25，正式来源均从Canonical恢复。
- 普通正文及 forward own-text 复用生产函数；转发 occurrence 保留 root/path 独立身份，按外层 timestamp 过滤，结果从 canonical root JSON 回读。preview 不进入正文。实验 B **64/64 count+top10 与生产一致**；Agent adapter 两侧另有 128 arm/case 检查及两组 session+时间 Scope parity；合成转发端到端测试覆盖 preview、Scope、恢复与 A 的真实无 metadata 身份。
- 生产 guard 检查 strategy、forward projection version、canonical revision/count、FTS 与 forwarded 总数；A 始终是实验库，没有伪造 v2 metadata，也没有旧策略生产入口。

历史记录 `temporal-browsing-cjk-lexical-recall.md` 和归档任务保留了 473,236 消息时的 `推荐` 0→157→187、全库 1596=LIKE、约 8.7–9.0 秒重建。已从历史原Trace恢复0命中的实际条件：trusted Scope为单会话，archive_latest前2天，时间区间[1786671390000,1786844190001)，limit=30、context=2/2、coverage=complete。记录中的初次诊断窗口14条与后续smoke的157/187条，仍缺少后两次完整原请求参数来核实是否同一过滤条件，不能仅凭文字将三者合并。旧 Trace/文字记录可以说明历史失败与修复过程，**不计入此次分子分母，也不宣称重跑了历史实验**。历史 resume-benchmark 的 lexical/semantic、Provider、sealed Holdout 同样不改写。

## Benchmark 与 Oracle 修订

64 条固定查询：短词20、连续中文12、中英混排12、英文/URL/代码控制12、不存在词4、单字4。57条有相关消息，7条空 Reference（4条不存在词及3条控制词）。短/长词人工选取真实主题和历史 failure；混排从原文扫描发现后选择技术/求职语汇，排除昵称等系统噪声。控制词保留无命中的 ImportError、HTTP 500、get_message_context，没有看 A/B 输出后换题。不是随机线上 Query 分布，也不是 fresh holdout。

首次按转义 LIKE 冻结 Reference 后发现原文 NUL：`LIKE '%模型%'` 对 `前文\\0后文模型` 返回0，而 FTS会搜索后段。首版输入/结果完整保留，标为 Oracle-invalid；新建 `oracle-v2`，用 **`instr(lower(content_text), lower(term)) > 0`** 枚举完整文本。{len(revisions)}个查询的 Reference 合计增加19个 query-message pairs，Query/Scope/limit/排序改变0；修正记录见 [oracle-correction.json](oracle-correction.json)。修正版 Reference 冻结后，复用完全相同 A/B索引重新查询及生产 parity，未选题或修改算法。 headline 仅使用修正版评分。

Reference 是 ASCII 大小写不敏感的完整字面子串，不是语义相关性；没有人工审核，**human_verified=false**。不存在同义词/语义问题的全库 GT。`HTTP 500` 的生产空白 AND 与整串子串 Oracle 不同；混排空格/标点等价也是 tokenizer 契约差异，不自动判成语义无关。分母是 query-message pairs，跨 Query 的同一消息可重复计数。完整参考与排名身份仅保存在被 Git 忽略的本地目录。

## 总体指标（57 个正例 Query；7 个空例单列）

Recall@10 = 前十相关数 / 全部字面相关数；Hit@10 = 前十至少一条相关；MRR@10 = 首条相关的倒数排名。空 GT 不计入这些分母。macro 按 Query 平均，micro 按相关消息聚合；Hit/MRR 的 micro 与 macro 等价。全深度覆盖枚举全部 FTS hits，不受结果10条截断；**不是应用已向用户返回全部消息**。

{header}
{chr(10).join(metrics)}

真实 Hit 为54/57→56/57，MRR倒数排名和54/57→55/57。总体返回项字面 Precision@10（sum TP / sum actual returned，少于10不补齐）为 **459/461=99.566% → 509/519=98.073%**（−1.493 pp，相对−1.50%）；不是人工语义 Precision。全深度字面误匹配2→341（+339），其中339来自混排。空例正确无结果6/7→6/7；四条预设不存在词两侧均4/4。HTTP 500两侧均有2条 AND命中、没有整串字面命中。

## 主要中文范围与分类

44条中文/混排查询：全深度 micro覆盖 **2,853/89,346={percent(cjk['A']['completeness']['micro'])} → 89,340/89,346={percent(cjk['B']['completeness']['micro'])}**，绝对+96.800 pp，相对+3031.44%；macro为21.819%→99.777%。Recall@10 macro **10.166%→14.676%**（+4.510 pp，+44.36%），micro **360/89,346→407/89,346**（0.403%→0.456%，+0.053 pp，+13.06%）。Hit@10 **42/44→44/44**（+4.545 pp，+4.76%）；MRR@10 **42/44→43/44**（+2.273 pp，+2.38%）。

32条纯中文查询（不含混排/单字）：全深度 **2,454/87,671=2.799% → 87,671/87,671=100%**；macro12.979%→100%。仅支持本次可穷举字面范围。20条短词的前十相关数两侧都是200：高频词已有10条命中时，扩大覆盖不会自动增加Recall@10；`推荐` 本次283→2485=Reference2485，并不等于Agent准确率从11%升到100%。

| 分类 | Query/正例n | Recall@10 macro A→B | Hit@10 A→B | MRR@10 A→B | 全深度 TP/Reference A→B | 漏召回 pairs A→B |
|---|---:|---:|---:|---:|---|---:|
{chr(10).join(classes)}

分类完整 macro/micro、每个 Query 的 metrics/分母见 [oracle-v2-summary.json](oracle-v2-summary.json)；上表全深度漏召回比例可按遗漏数/Reference复核。无相对分母时不声称无限提升。

{category_changes(results)}

## 失败、排序退化与边界

- A=0、B有前十相关：`大模型infra`（0→122 hits，10条前十相关）、`字节hr`（0→101 hits，8条前十字面相关；Reference82）。零基线不计算相对提升。
- 三条 top10退化：{'; '.join(f"{row['term']} {row['A']['top_true_positive']}→{row['B']['top_true_positive']}" for row in regressions)}。混排 MRR 从10/12→11/12总体改善，但不能掩盖具体排名退化。所有A的全深度hits都保留在B内；退化来自新召回项和排名截断，不是原有候选被删除。
- B中混排全深度仍漏6条：`华为ODDO`（1条）、`字节hrbp`（1条）、`aagent开发`/`mdagent开发`（2条）、`caludecode源码`/`opencode源码`（2条）的 ASCII前后缀仍受 exact token边界限制。其余339个额外mixed命中主要来自“AI 应用”“AI/算法”“字节 hr”“agent 开发”等分隔写法；对完整字面串是FP，对语义问题可能有用，当前没有人工标注去断言。
- 单字4条：仅 **10/44,703 → 20/44,703** 全深度覆盖；`荐`两侧0/2504。bigram不包含内部unigram，B并未解决单字子串查询。
- ASCII控制的前十指标不退化；全深度coverage上升，但`GitHubeducation`、`GithubPages`、`JavaScript`等词内子串仍不被 exact token覆盖。非Han字符没有被改写不意味着混排文档的分词边界完全不变。
- NUL假FP已通过独立Oracle修订排除；未为此改生产算法。217未展开forward节点不作为已知正文补齐；Reference只对可恢复内容穷举。

所有64条的Query/Scope/Reference、FP/FN IDs及真实正文样例位于本地 `oracle-v2/failure-cases.json`。确定性回归覆盖NUL Oracle、混排分隔符FP、空GT分母、生产keyword/AND、forward Scope与恢复。没有把已知限制用fallback或新策略掩盖。

## 性能与空间代价

同样823,835条投影输入，A/B的FTS插入+commit分别 **{build['A']['insert_commit_ms']/1000:.3f}s / {build['B']['insert_commit_ms']/1000:.3f}s**，B增加{(build['B']['insert_commit_ms']/build['A']['insert_commit_ms']-1)*100:.1f}%；一次构建，未估计方差。独立FTS文件 **{build['A']['bytes']:,} / {build['B']['bytes']:,} bytes**（{build['A']['bytes']/1048576:.2f}/{build['B']['bytes']/1048576:.2f} MiB），B增加{(build['B']['bytes']/build['A']['bytes']-1)*100:.2f}%。共享canonical/forward投影准备成本不计入双方FTS差值；首轮完整生产rebuild计时因manifest构造失败未保存，明确 unavailable。

Agent与测试结束后单独延迟复测：64 Query×5 warm repetitions=320样本/侧，逐题交替A/B。count+top10 SQL中位数 **{a_time['median_ms']:.3f}→{b_time['median_ms']:.3f} ms**，P95 **{a_time['p95_ms']:.3f}→{b_time['p95_ms']:.3f} ms**。这是SQL核心耗时，排除了readiness全表校验、Canonical正文恢复、自动上下文和Provider；不能当作完整工具/线上SLA。频繁词更多匹配增加count/sort代价。此前两轮时序也保留；Oracle-v2重跑与Agent并发，故质量结果可用，headline延迟取独立结束后复测，而非挑选较低值。[latency-final.json](latency-final.json)包含每次原始样本。

## DeepSeek Flash 真实 Agent（独立于离线指标）

官方 `deepseek/deepseek-flash`，`https://api.deepseek.com`，显式读取本地.env并校验密钥存在，未覆盖/记录密钥。复用真实 `TrivaeApplication.query()` 和 EvaluationRunner/SQLiteEvaluationStore；两侧同一代码、Prompt、标准路径override、工具surface（lexical_search/get_message_context）、result scope=10、context=0、现有轮次预算。只注入已通过parity的实验lexical reader；不覆写生产readiness，不伪造strategy。两侧canonical/forward恢复一致。

这是lexical-only受控Agent，不是默认全工具Agent。每题一次；8题中的GitHub A在计数异常检查时主动中断，不重试，不剔除。最终15条returned runs（10 completed、1 completed_degraded、4 failed）+1 aborted；7完整配对中两侧各5/7成功，没有completion uplift。5条可回答正例中，最终Evidence至少包含原始完整关键词为A **4/5**、B **5/5**；每题最多3条必要字面证据的配额为12/15→15/15。这只证明本次Evidence命中，不等于答案事实正确率，不能由1个case推导稳定E2E提升。

| Case | A（direct相关；final相关/引用来源；调用/Token/时间） | B |
|---|---|---|
{chr(10).join(agent_table)}

- 所有引用来源都能从Canonical恢复；来源存在/字面相关不等于每句话得到正确支持。AI诊断看到B把“人工智能”说成“三个字”（实际4字），`ai应用开发`的回答用“最早/最具代表性”概括BM25候选，且把276个FTS hits称为完整字面串数量（Reference249）。保留为答案/表述失败，不标human_verified，不给语义citation correctness率。
- `大模型infra`的A改查infra后交付degraded答案，但最终来源0/3含原始完整词；B有4/4含原词的来源。该差异与离线token漏召回相符，单次运行不足证明稳定收益。
- 不存在词A/B及`荐`A/B均在finalization被 `INVALID_FINAL_OUTPUT`拒绝。Trace错误为 `zero-result final answer lacks verified complete-and-empty retrieval evidence`；检索返回partial，因为有217个forward gap。不存在词是覆盖/无结果合同边界；`荐`还叠加真实检索漏召回。Provider全部已记录响应为200，不将这些当成Provider失败。
- Python A一次Trace为collector_degraded，日志仅给出TraceStoreError而无可确认的底层原因，不能断言锁竞争。该run缺失sequence=1（query.received），其余2–30存在；完整Trace审计不可用，不重跑或假装完整。
- 首批hook错误挂在httpx，而当前SDK走httpx2。原0计数保留但标为无效；从Trace/usage核对首批17个完成请求，中断项1个完成响应、另1个可能在途。后续7runs由正确httpx2 hook记录14次200。**确认{confirmed_requests}次HTTP响应，计入取消中的请求后总尝试范围{confirmed_requests}–{confirmed_requests+1}，未超过40**；无法恢复取消请求的精确计费，不伪造整数。
- 15条已完成记录总Token **{tokens['total_tokens']:,}**（input {tokens['input_tokens']:,}，output {tokens['output_tokens']:,}，cached-input {tokens['cached_input_tokens']:,}），中断项已确认另6236 tokens，未完成请求usage未知。未返回真实成本金额，因此不推算费用。

[agent-summary.json](agent-summary.json)为脱敏运行摘要；私有原始结果、完整Artifact、Trace、review packet、HTTP列表和计数修正均保留在本地。审核状态是自动字面检查/AI诊断，没有人工答案裁决或付费Judge。现有索引与Prompt不为此次结果重调。

## 结论与可引用边界

本次证明：在固定真实快照的32个纯中文字面查询中，v2消除了unicode61的连续中文子串漏召回；44个中文/混排查询的micro全深度覆盖从3.193%升到99.993%，同时暴露6条混排漏召回、339个分隔写法FP、3条前十退化及单字限制。整体Recall@10提升有限且远小于全深度覆盖提升，构建、磁盘与SQL延迟均增加。

不能证明：Agent事实准确率达到99.993%；任意自然语言语义召回完整；单字支持；线上延迟SLA；跨语料泛化；全默认Agent或稳定E2E质量提升。查询为人工选词/同一语料，无盲测统计推断。后续若要优化，应分别用真实需求决定混排分隔语义、ASCII前后缀和单字支持；本任务不引入新tokenizer、LIKE查询fallback或Prompt改写。

简历证据与面试说明见 [CJK检索实验-简历与面试.md](../../../interview-docs/CJK检索实验-简历与面试.md)。工作验证：最终完整pytest **1187 passed/1 skipped**，专项7/7通过；ruff与mypy通过；原始ID独立指标核验、公开摘要一致性和文档链接检查通过。提交及推送身份见Git记录。
'''
    write_new(PUBLIC / 'metrics-derived.json', {'cjk44': cjk, 'pure32': pure,
                                               'reference_pairs': 147362, 'reference_revision': 'oracle-v2'})
    (PUBLIC / 'report.md').write_text(report, encoding='utf-8')
    canonical.close()
    corpus.close()


if __name__ == '__main__':
    main()
