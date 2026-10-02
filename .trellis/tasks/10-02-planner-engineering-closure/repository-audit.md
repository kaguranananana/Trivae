# 当前生产身份与历史审计

起点 HEAD 221f57a，codex/planner-p1-stability，working tree clean。fetch 后 origin/main=12f2f75，behind=0/ahead=14；四个用户指定提交均在当前 ancestry，无历史重写需求。

## Confirmed facts
- 2da57b9 恢复 68286d5 的 canonical P1 文本；Adapter 精确官方 DeepSeek Flash Planner boundary 保持 none。
- 23a3e9b 的 Planner-only 单变量实验 6/8 low、8/8 none 有效，none 平均 1.301s、low 6.700s；这不是最终答案质量证明。
- 361a38e targeted E2E 16 runs/63 HTTP，none 8/8 有效、low 6/8；none 2 个最终质量回退、3 改善、3 相同，Gate A 保持。
- 221f57a 固定两个 Plan 各 2 次，仅 16 downstream HTTP；原 none Archify 错误未复现，出现同 guidance 的 Tool arguments/context/Evidence/synthesis 方差。无法只归为 Answerer。
- Frozen replay 4/4 参数误用，7 次 MESSAGE_NOT_FOUND。source resolver 已正确；schema 缺字段 description、Tool description 混合两类 ID，模型可见语义有歧义。
- low-r2 7k=2026-07-23T09:25:23Z、9.5k=2026-08-06T02:40:20Z，delta=1185297 秒；Evidence finding/criterion 和 Answer 增加同日关系，retrieval 时间事实正确。

## 当前入口
Application 默认 RuleRouter（existing LLM completion low + 当前环境 Jev enabled/shadow）→ planned 时一次生产 SoftPlanner(P1/none)→ shared OpenAIAgentsRuntimeAdapter(low)。Router 与 Planner completion 使用独立投影；Runtime SDKModelSettings 新建，不共享可变 treatment settings。Runtime 8 turns/3 tool rounds/16384，Planner 2048/20s/temperature0/JSON，client retries=0。
Thin Planner 不执行 Tool，不拥有 state/workflow/replanning，Plan suggested_tools 只是 hint。实际 Tool/参数/检索/Evidence/Answer 由 Runtime + 既有 Finalizer 路径负责。正式实验的 existing forced route 绕过 Router/Jev，不将 shadow 干扰混入 treatment。

## 八条 GT
固定使用既有 loader 显式列出的 8 IDs；snapshot 473236 messages/14 sources、FTS473236、Qwen3-0.6B/1024/last_token/normalized semantic completed/54267 chunks。所有 gt.* finding provenance 已 adjudicated；utility.structured_answer 仍非人工标签，不冒充 GT。required evidence 在相同 Scope 通过 canonical read 核验，preflight 保存内容/时间。
- dependent/context 的相关标注 partial，不推出 corpus-exhaustive recall。
- cite-archify GT 只列 exact archify 三条消息，不含7k邻居或所有事实关系；关系额外复核，原 GT 不改。
- temporal-30d 仅 coverage/truncated/zero GT，主题语义没有完整人工 GT，必须逐条核验引用。
- ranking 单一最高会话 qq:677019167=224，不证明并列处理；aggregation text814/reply17；zero 为已确认空窗。

## 无 Provider 的问题与修复
preflight-v1 因 ControlledVariant 禁止包含 api_key_configured 字段而失败；runtime_configuration 改用同一 settings 的非凭据字段，credential configured 只放独立安全 preflight/manifest。原目录保留，0 formal attempts/0 paid Provider calls。preflight-v2 通过并预热既有 semantic extra；没有新 Planner treatment。
新测试编写阶段的 SDK ToolContext/stream 方法、scope limit、intent 类型错误按真实既有接口修正 fixture；没有改变生产行为迎合测试。

## Lint 范围
仓库规定检查为 ruff check src tests；本轮扩至 src/tests/evaluation/scripts 全通过。额外 ruff check . 发现62个既有错误、21文件，逐文件确认与221f57a字节相同，均为管理/历史脚本。本轮不修改这些无关脚本，完整诊断保存于 ruff-root-diagnostics.json。
