# 最终有界实验交付审查

独立 Codex Agent 直接完成 trellis-check 收口，非人工裁决。只读真实工件、原 Case/GT、最终公开报告/机器摘要/候选删文/预算授权记录；0新增实验 Provider 或 Judge请求，未改源码、Prompt、GT、Case、冻结条件、账本或原运行工件，未提交。主 Agent 维护的 task/implement/spec 链接未并发编辑。

## Findings（fixed）

- `experiment-report.md` 开头最终结论章节指引仍写第9节，实际最终总账与否决在第10节。机械修正为第9–10节，未改变结果。
- `experiment/candidate-edits.json` 的 B02 status 原 “retained in cumulative candidate” 容易混淆保留的是删除还是原规则。改为明确 P56/P57 指令正文保留、删除未采纳；与真实 C01/C02 父链、字符数及原结论一致。

## Findings（not fixed）

无未解决审查问题。初读时 `results-summary.json` 顶层单值源码版本缺历史scope，已通知主Agent并复核其修正：改为 `historical_quality_runtime_code_version`、明确through52范围，列各run实际版本及阶段loaded源码增量，最新版本0f6d531。原逐run code_version及配对代码一致性保持正确；机器字段结构由主Agent统一修改，本Agent未并发编辑。

未发现需要修改最终数字、TS退化方向、生产否决或隐私边界的实质问题。

## 独立真实工件核验

### 请求、运行与冻结

- 31个公开 phase 列表对应的原 provider-ledger 逐项求和139，原累计139/140、剩1一致；120→140的授权记录保留累计108、没有reset，既有phase未改写。
- 去重60 run与机器列表一致；新snapshot57 run、16 distinct Case，其中Runtime completed40，正式Query successful39。差1为已精确复现的Finalizer拒绝，不能把Runtime40当40正式答案。其它18条新snapshot Query未成功。
- run工件真实请求136，另三个Router/Planner组件HTTP共3，合计139；模型和High参数均一致，保存的input不含type=reasoning隐藏重放。
- 最终B01 13配对（用户节点12+旧SQL1）均按真实工件重新关联A/B、核对完整conditions相等及整串Prompt：A为生产20450字符，B仅删除P64原片段35字符。原 production SYSTEM_PROMPT仍20450，实际采纳删除为空。
- 用户节点阶段原账本合计65 HTTP，逐transport event检查无start_tls.failed；其中旧sharing quota失败仍保留，不能把65次写成65成功答案。后续恢复成功与本地预算授权是两个事实。

### 效率与Usage

独立对13对原 operational_measurements 求和，与报告及机器摘要完全一致：

| 合计 | A | B01 |
| --- | --- | --- |
| HTTP | 34 | 32 |
| input | 449060 | 405591 |
| output | 8791 | 8982 |
| total | 457851 | 414573 |
| cached input | 37120 | 27648 |
| latency ms | 401248 | 358498 |

所有去重run可用Usage合计120请求；另真实metadata捕获1请求为7278 input、41 output、7319 total，Router成功返回Usage1请求为144 input、106 output、250 total。相加122已知请求，与报告下界1639148 input、28826 output、1667974 total、83584 cached input、4027 reasoning相等；139−122=17未知/未完整汇总，未填零。货币费用明确未知。报告未把34→32或Token减少归为35字符稳定因果收益。

### 质量及拒绝判断

用户节点12对均由此前完整GT/Canonical/实际投影/最终引用复核支撑：改善1、合格持平9、共同不足1、退化1。加早期SQL持平1，最终B01为13对：改善1、合格持平10、共同不足1、退化1。C组3对为改善2、共同不足1，未混入B01；全部16个配对单位是改善3、合格持平10、共同不足2、退化1，不是16个独立问题或人工通过数。

最终TS A真实送达并最终引用固定critical target，B01实际全部工具投影未送达且未最终引用，1/1→0/1。相关替代内容有证据，不改判事实错误，但不能抵销critical缺失。intern两侧共同target缺失仍单独列不足；三条无有效Baseline的Case及所有工程失败保留，不纳入好结果或用失败A计候选胜出。

报告明确拒绝B01、恢复C01/B02/P33相关删文，生产删0；同时区分“未证明P64删除直接造成退化”和“没有足够证据通过本轮门禁”。原human-only、blind pairwise ReviewPolicy仍pending，Agent审查未伪称human。没有为了补过再采样、换GT或放宽Host预算/positive proof。

### 隐私与可复现边界

阅读全文及对四份公开文件的私有locator/uid/凭据扫描，未发现私聊原文、作者身份、私有来源locator、凭据、隐藏reasoning或数据库正文。真实模型输出、工具投影、Canonical及完整Trace保留在ignored目录，公开克隆无法独立重放私有语料的限制明确披露。源码commit身份和公开Case/阶段名仅用于审计，不替代私有证据。

## Verification

- 本轮仅文档，`git diff --check`通过；JSON读取/13pair条件与Prompt核验/效率聚合/31ledger及65HTTP检查均通过。
- 最近源码0f6d531已经独立增量审查；本Agent此前全仓Ruff通过、mypy128文件通过、相关77测试通过。主Agent源码全量证据1180 passed、1 skipped已在报告明确，本轮文档修改未重跑全部测试。
- 未触发新网络或真实实验请求，未修改原失败工件/GT/Prompt，不提交。

## 收尾语义

可将本轮有界实验按明确否决结果交付收尾；completed只表示修复、真实实验与报告交付结束，绝不表示候选达到质量门禁。既有小余量投影/SDK分类、失败Usage、Router/Planner真实JSON/超时及人工复核未完成仍是公开剩余风险。任何后续主链路修复和重新评估应使用新的明确冻结身份，不能覆盖本轮负结论。
