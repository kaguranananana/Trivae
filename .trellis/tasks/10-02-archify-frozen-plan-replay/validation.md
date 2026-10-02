# 验证记录

## 工程验证

- 新增 7 个 provider-free tests；相关 replay/E2E/query 回归 44 passed。
- 全量 provider-free 回归 648 passed（运行中 16.32s；实验完成后 16.23s）；Ruff 检查 src/tests/replay runner/analyzer 通过；mypy src 115 files 通过。
- 首次 fixture 缺少 max_turns：按现有 ModelSettings 必填契约补齐，没有修改生产默认值。
- 测试暴露 SDK reasoning 为 Pydantic 对象：修复 runner 为正式 to_json_dict()，保留实际 nullable 字段，effort 固定 low。
- 首次预检发现 snapshot created_at 每次 materialize 不同：根因是观测时间与数据身份混淆。排除唯一观测字段，完整数据身份仍严格比较，新增数据漂移回归。0 formal attempts / 0 DeepSeek HTTP，失败预检目录保留。
- 自动分析初版错误匹配 model.turn.completed：按真实 normalized operation=model.turn、phase=completed 修复，得到 16 model turns，与 16 HTTP 一致。raw/Trace 不改。

## 真实实验完整性

- attempts/results 各 4 条；evaluation_runs/evaluation_results 各 4 条；4 terminal traces、262 events。
- HTTP request/response 各 16 条，全部 200；completed model turns=16；无 Planner HTTP、transport retry 或 timeout。
- 两侧 initial actual HTTP 除精确 guidance 外相同；每个 guidance 两次 first HTTP body 完全相等。
- 所有源 Plan、Case、runner、生产文件逐字相等；Snapshot 除 materialize created_at 外全部相等。
- 21 Provider tool calls 与 21 normalized Tool calls 顺序一一对应，7 次真实 source_id/message_id 误用保存；未新增兼容或修复。
- 判断为未盲 root 事实审计，与自动指标分开；未冒充 independent blind/human review 或质量等价。
- 132 个 frozen 文件最终逐字相等，报告链接有效；task.py validate 通过。既有 Runtime 指南超过自动注入字节上限的警告已记录，本轮直接读取所需章节，不依赖截断注入。

交付纳入 Git；任务目录保留原位，原 16-run 的报告仅追加后续实验链接和 normalized/Provider 参数归因说明，原始 runs、盲审判断与指标不改。

主结果、边界和后续动作见 [report.md](experiment/report.md)，具体 claim/source 核验见 manual-audit.json。
