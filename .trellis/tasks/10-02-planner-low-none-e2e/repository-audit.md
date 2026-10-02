# Repository audit（正式 Provider 请求前）

- 起点 HEAD `e75b34711daf4c8c1825dedfa219a501a8cf154b`，初始 working tree clean；本轮只新增 experiment runner、tests 和任务工件。
- 历史来源：`09-28-planner-p1-low-none` 的 PRD/design/implement、raw records；读取当前 Evaluation Runner/checks/benchmark metrics、v3 validation/design，未读取 Holdout 或 Calibration bundle。
- canonical loader：`run_planner_only.py::load_cases`，按 manifest 显式挑选固定 8 IDs；没有遍历并加载其它 Case。
- 当前生产链：EvaluationRunner → Application.query → existing forced planned override → SoftPlanner → 同一 SDK Runtime → canonical Retrieval/Tools → Evidence/Finalizer → Conversation commit。
- 生产官方 DeepSeek Flash Planner 已默认 none。本轮通过正式 `create_application(planner=...)` injection + existing completion override 重建 low/none，保留所有生产 skip/degraded/error 契约。
- ModelSettings 来源：dotenv 后 `load_settings()`，DeepSeek official endpoint、deepseek-flash；Planner 2048、20s、temperature=0、JSON mode；Runtime 8 turns、3 tool rounds、16384 output、low thinking 两侧一致。
- SDK client `max_retries=0`；本地 OpenAI 3.5.0 使用 httpx2 2.12.0。实验 observer 在相同 HTTP 类型上透传，不能用旧 httpx transport 假设。
- 当前 EvaluationRun query snapshot、DeterministicCheck、Tier1 metrics 可复用；semantic correctness/citation entailment 仍须独立盲审，不能从 validated artifact 推出。
- Trace debug 有既有 capture bounds，raw HTTP requests 和 QueryResult ToolResults 提供完整公开模型输入/结果；不会扩大生产 capture policy。
- Snapshot：473236 messages，时间 `[1753011800000,1786847688000]`，14 sources，FTS count 473236；semantic index completed，54267 chunks，Qwen3 0.6B/1024/last_token/normalized。
- 固定 GT 的 ranking 第一名仅 `qq:677019167=224`，不含并列最高值。仅可判断本 Case 排名是否正确，不可声称验证了真实 tie completeness。
- 没有 retrieval result cache；每次新 conversation，无 history。Provider prefix cache 不能通过改生产配置关闭，将保存每请求 cache usage，并作为顺序/性能边界说明。
- `preflight-only` / `preflight-v2` 是 provider-free runner 检查失败（Variant secret-field contract / callable instructions serialization）；`preflight-v3` 全部通过，没有真实 API 请求。
- 首次 formal 启动在 semantic preload 失败：虚拟环境缺少既有 semantic extra，未写任何 attempt、未发任何 Provider request。原目录保留为 `startup-environment-failure`，按已有 lock 安装 extra；正式 16-run 分母从首次真实 attempt 开始。
- code freeze 用源码/runner/8 bundles/manifest/pyproject/lock 的逐字副本与前后 equality，不新增哈希；执行 SHA + dirty state + frozen files 共同标识未提交实验代码。
