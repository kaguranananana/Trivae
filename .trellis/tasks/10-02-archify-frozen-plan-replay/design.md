# 设计与变更边界

最小缺口：既有 run_p1_e2e.py 只支持重新生成 Plan 的 16-run batch，没有固定 Plan 重放。行为位于已有 create_application(planner=...) 注入边界。

新增 run_frozen_plan_replay.py，通过生产 SoftPlanner parser 读取保存的 Plan，逐字段确认不被归一化改变；FrozenPlanner 只返回该 Plan，不构造虚假的 Provider observation。生产 Orchestrator 仍渲染 guidance，生产 Runtime 仍自主选择 Tool、Evidence 与 Answer。

复用原 runner 的 HTTPRecorder、usage_for、append_json、write_json、freeze 逻辑，以及现有 EvaluationRunner。新增 provider-free tests 验证 4-run counterbalance、解析原样、注入不发 Planner 请求、输入隔离与真实调用路径。

顺序 seed=20261003，两块 AB/BA，每侧各两次；数据 snapshot、源码与 Runtime 参数对照上轮 frozen/manifest，保持新 conversation 和同一预热 embedding。所有下游使用生产 low reasoning；treatment 仅标识 Plan 的来源，不表示本轮调用该 reasoning mode。

预检比较实际 Agent builder 的 instructions/input/schemas/model settings；首个真实 HTTP 请求再与上轮及另外三次逐字段比较，唯一允许变化是 plan guidance。HTTP ledger 不保存隐藏 reasoning 正文，未知 usage 保持 null，不估算金额。

本轮以完整 ToolResult 与 Citation 逐条事实核验为主，保存未盲的人工判断，不冒充独立盲审或引用 precision 总分。两次/侧只能初步检验重复性。发现生产错误只记录，不当场修复。
