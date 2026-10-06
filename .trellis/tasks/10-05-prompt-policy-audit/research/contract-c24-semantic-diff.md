# C24：公开已有空白AND匹配契约

Iteration ID：C24。Policy scope：lexical keyword字段的既有匹配语义。Risk：低工程／模型选择需实测。Prompt lines affected：0。Deterministic owner：LexicalQuery.terms → _fts_match_expression → FTS5。Tests required：两名称真实Schema、四消息SQLite fixture、static、UI targeted。Expected Provider calls：probe1 + paired6；Maximum：1 + 8，累计上限80（开始41）。

Removed / Moved / Reworded：无Base Prompt变化。Added：keyword字段说明空白分隔的term使用AND且不必相邻；无特定case词、无查询改写、无fallback、无新guard。Unchanged high-risk policy：discussion/negative/time/stop/routing原文字节与顺序。

输入是原字符串；输出是原有AND命中集合；依赖现有typed input/FTS；成功是多个词可在同消息非相邻或逆序出现，两单词消息不命中；失败保留真实检索状态。fixture必须显式构建derived index并使用normalized_content，初稿生命周期/字段错误已修正，断言未放宽。L0两Schema说明缺口复现；AND读取本身已经存在，不虚报新增实现。

UI真实问题：原Base及P04均未把推荐/第三人评价送入模型；skill628取100，UI效果不匹配实际词。零Provider真实读取ui skill仅3命中且GT可达。semantic index state实为completed/473236覆盖，partial是candidate pool/expansion，不是缺索引；不得据basis字符串误归因。

此改动改变公开Tool schema description，旧冻结合同不再可复用；后续须fresh同条件Baselines。真实Provider改善仍待验证，不宣称已修复语义blocker。
