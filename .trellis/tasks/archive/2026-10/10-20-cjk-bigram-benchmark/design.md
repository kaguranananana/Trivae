# 设计与变更边界

缺口：已有 Evaluation 支持 lexical/semantic，而没有隔离的旧 unicode61 对当前 v2 单变量实验。新增实验 runner（evaluation/experiments/cjk-bigram-v1/），不将旧策略接入 src 生产模块。复用生产 SQLiteLexicalIndex 建立转发投影及 Candidate，再从同一 canonical/forward 正文创建独立实验 FTS。A 原文、B 现有 normalize 函数；同一 SQLite、Scope、BM25/tie-break SQL。B 逐题与生产 count/top10 parity 校验。

SQLite backup 固定快照；真实聊天、ID reference 与 trace 保存在 ignored data/evaluation/cjk-bigram-v1/；版本化配置/脚本/脱敏结果独立保存。先冻结输入 JSON，拒绝覆盖正式结果。LIKE 的定义为 SQLite ASCII 大小写不敏感字面子串（转义通配符），并枚举 canonical forward-own text 及全部 occurrence；不是自然语言语义 GT。歧义查询也只评字面，不冒充 human_verified。

关键模块七问：目标是测量现有策略；最小输入为快照+查询+Scope，输出为指标与原始排名；依赖 storage 投影/GT/score_ranking；边界在实验 adapter 而非生产；失败暴露 traceback 与原始产物；使用 parity、真实 A/B 和测试证明；不改算法、模型 Prompt、历史记录、生产库或语义索引。

Agent 先预检 env（只输出非 secret identity），同一官方 Flash Application 真实执行。严格旧索引不能通过 production readiness；若无法在不扩展生产架构情况下注入受验证 adapter，保留 Candidate-only 诊断并声明 E2E uplift unavailable。最多 40 HTTP，总预算计入失败请求；无额外 Judge 调用。

## 实施证据带来的设计修订

- 80个source使DatasetSnapshot生成的身份超过通用4000字符上限。仅修复Evaluation结构化身份的构造/反序列化，普通短标识和检索算法不变；真实表构造、Case round-trip已测试。
- 原始LIKE Oracle在NUL后漏读；保留首版冻结/输出，另建oracle-v2，instr枚举完整文本，64个Query及Scope未变，8个Reference Case合计增加19个pair（具体Case数量以oracle-correction.json为准）。修正版先冻结，再用同样索引重跑，不择题。
- 两侧真实Agent均通过独立ExperimentLexicalReader接入已有LexicalRetrieval对象；只替换count/hits，其余canonical恢复/上下文走同一owner，不覆写readiness、不伪造metadata。128 arm/case与两组Scope parity已通过，因此可做严格lexical配对，无需Candidate-only降格。
- 当前OpenAI SDK走httpx2。首批hook未捕获请求，8条完成runs有17次调用；另1条GitHub A中断前1次响应、至多1次在途，续跑预扣19。后续7条14次HTTP均200；确认32响应/最多33次尝试，不重试中断A。
- Agent与离线修正版并发时的时序不用于延迟headline；最终独立time阶段测64×5样本/侧。Python A的TraceStoreError底层原因未知，不猜测锁竞争，不把不完整Trace标为完整。
