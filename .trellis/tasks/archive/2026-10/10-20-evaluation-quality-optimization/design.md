# 实验设计

## 边界与数据流
历史审计 → 原消息存在性核验 → 当前快照新版本Case → 冻结实验条件 → EvaluationRunner → TrivaeApplication.query → Artifact/Trace/Evaluation → 既有metrics与独立语义review。
复用生产装配与受控Variant，不自建Agent。仅允许已证实根因所在owner的最小修复；具体文件待Baseline Trace确定。

## 评分预注册
有证据答案通过：执行完成、必要事实正确、关键证据支持、引用有效、满足核心要求，五项全部通过才pass。人工输出审核未完成保留pending，Assistant源证据复核可给provisional，不计人工通过。
关键证据覆盖：最终Artifact包含已核验GT target的数量/固定target总量；另报tool-return与model-visible层，区分检索和证据选择。执行失败在无条件coverage中记0，既有条件指标单列。
事实引用支持：逐必要事实审核support/unsupported/pending；引用可解析不等于支持。保留原始分母、未审项与对照变更。
执行成功、Token、延迟以生产结果与实际usage为准，货币成本缺失不推算。

## 冻结与预算
Baseline execution commit当前8def8d7；准备脚本可单独提交但不修改质量逻辑。SQLite backup得到固定canonical副本，派生semantic索引同样固定；GT保留历史provenance并新增版本/快照适用性pending，不伪造人工再裁决。
工具集合、路由、Prompt、模型设置和预算两侧一致。全局发送前持久化HTTP计数，120封顶，无主动重试。开发Baseline先运行，定位修复后再运行Candidate；独立集用未参与本次调参的预登记Case，明确历史曝光，绝不称blind/fresh。

## 七问
1. Responsibility：修复已证实质量缺口，不迁移职责。
2. Failure：历史问题可能已修、GT可能漂移、Provider可能失败、内容需人工。
3. Observability：debug Trace、Artifact、Evaluation SQLite、实际HTTP账本在ignored目录。
4. Attribution：分别判断direct recall、context、model visibility、evidence selection、generation、citation与external/configuration。
5. Decision：先Baseline再选择最小owner修复；不新增无依据fallback或预算。
6. Verification：固定GT与条件配对实测；provisional与human分开。
7. Regression：真实根因对应非样例硬编码单元回归及非目标验证。

## Baseline后选定根因与最小修复
8条Baseline于首次质量修改前完成，21次HTTP，8/8成功。miner问题真实遗漏具名资源：semantic与一次context共3HTTP，未取得4个GT target，正文只给方法建议/无名Skill。离线正式LexicalRetrieval证明从问题和已见结果可构造的“简历 skill”43命中内target ranks20/21/23/24，“简历 github.com”26命中内ranks7/9/11/12；单独“简历”前100和“项目经历”不能覆盖，故不是随意加宽预算即可修复。
根因定位为Tool Selection / evidence sufficiency：把与用途有关的方法建议当作工具发现问题的充分结果，未进行现有策略允许的insufficient后续检索。非embedding故障、非Host裁剪。最小treatment仅prompt.py现有工具选择段澄清具名资源充分性，使用问题用途与已观察资源线索的focused lexical；不含Case关键词/ID，不增工具/轮次，允许部分检索，不强求穷尽。没有改变Scope、Finalizer、引用标准或检索算法。
runner只新增显式prompt-treatment身份比较：仅base prompt及其initial instructions前缀可变，后缀和其他条件逐字相等；用于审计此单变量，不是另建评测框架。其余研究候选（reply结构、source-hit截断披露）没有当前坏答案因果证据，不在本次修复。
验证：开发8对现有Baseline→Candidate；Candidate冻结后12条预登记旧Development不参与调参回归，A从8def8d7源执行，B从候选commit执行；未完成人工语义审核，全部assistant_provisional。
