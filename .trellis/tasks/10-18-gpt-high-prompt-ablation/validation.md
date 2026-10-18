# 适配阶段验证

- 原始回归：新增配置/HTTP测试 2 failed（字段缺失）；实现后相关 58 passed，扩展多轮和冻结漂移后 60 passed。
- 首次 static 暴露 httpx/httpx2 client 联合赋值类型差异，改为在各具体 client 安装同一 hook，保留类型边界；未加 cast/ignore。
- static：Ruff 通过、mypy 128 source files 通过、312 passed；Provider/OAuth/query/completion/capabilities 80 passed。
- 全量：1155 passed, 1 skipped（25.87s）；随后新增两项测试相关 60 passed。
- 实际账号目录确认 gpt-6.1-sol；目录读取不计推理 HTTP 预算，未执行推理。
- Runtime、Router、Planner Mock HTTP 序列化均 high + summary auto；失败也计数；多轮 2 次真实 Mock transport sends；超额前拒绝；新 budget 实例不能重置总量。
- 捕获移除隐藏 reasoning replay，保留公开 effort 与可见 function_call_output；冻结实际 provider projection 并拒绝 effort drift。
- 生产 Prompt 20450 字符，未修改。
