# R2：语义命中到消息容量保留的单变量实验

2026-10-30；承接Z Code R1。Baseline为003642b3，Candidate只改变semantic expansion的核心消息保留优先序：字面证据仍优先，其余核心按检索排名保留。100条容量、候选池、Top-K、硬过滤、展示时间序、Prompt均不变。

假设：在没有完整短语字面命中、核心消息合计超过100时，Baseline把chronological display order当selection order，能把dense rank 1的整个child丢掉。Candidate应恢复这种目标，但不保证答案质量。

先红后绿：120条/12个chunk，rank与时间反序；另加入最旧字面消息，验证字面优先与最新高rank可同时保留。Baseline两项均失败，均丢失rank1的10条消息；不改断言修实现。

离线A/B复用R1全部51个semantic pool，读取master两库mode=ro，不重新embedding、不新建Application、不用模型；以正式read_message_range精确恢复core，不以数字ID判断包含。先核对每次Baseline的accepted chunk和expanded ID集合与R1保存结果相等。比较GT消息每调用出现次数、整块零消息chunk和top-rank丢失；所有Candidate仍≤100条。输出在ignored data/evaluation/agent-quality-codex-20261030/。

预设决策：若无GT净增益或出现GT退化，不直接保留Candidate；调查退化机制后另立实验，不围绕单题加规则。若有净增且GT无退化，通过完整确定性回归后进入真实Agent配对验证。真实阶段至少覆盖失败题05、对照题04以及未参与调参的题08/10，固定主Prompt B，各臂重复两次；最多16个Run/16个Judge，受250/32累计账本约束。Provider失败明确停止，不自动更换Provider或补跑。

停止条件：离线证伪；真实质量发生重要退化；预算/Provider边界；或本假设证据已充分。一次检索收益不称为总体答案提升。

## 真实实验前补充（按精确离线证据确定样本，尚未调用模型）

精确重放显示05的GT不在所选child正文，不能把它当作本修复的直接命中断层；不再以数字parent区间包含主张05可被本修复解决。改用01/07（诊断Case）及08/10（检查其他任务回归）各臂重复两次，共16 Run/最多16 Review；都是既有Eval v1题，不是fresh holdout。先执行08一组检查Provider与完整落盘，出错即停止该真实计划，不自动重试。质量指标保留Judge v2.1两轴、原事实清单（独立区分语义覆盖与来源ID）、运行失败与预算；不以token下降替代质量。源Prompt固定主B，唯一处理变量是100条容量保留优先序。

预设保留边界：51调用离线目标无退化且有净增可支持工程层修复；只有实际Agent/Judge重复对照也支持关键事实改善、没有重要退化，才可报告答案质量收益。若Provider中断则仅报告工程收益，真实优化状态仍待验证。
