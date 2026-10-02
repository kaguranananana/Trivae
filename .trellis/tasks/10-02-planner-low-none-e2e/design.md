# 设计与审计

起点 HEAD=e75b34711daf4c8c1825dedfa219a501a8cf154b，working tree clean。当前生产官方 DeepSeek Flash Planner 默认已为 none；本轮只以已有 completion override 构造 low/none SoftPlanner，注入现有 Application planner 参数，不改变生产实现。

复用历史 case loader 和 EvaluationRunner。Runner 的 snapshot metadata 是当前生产 Evaluation 输入，与 Planner-only compact snapshot 的动态段不同；P1 builder/template 与两侧全文一致，分别归档输入，不混淆历史实验和本轮。

单一 Application/Runtime 与真实 semantic provider，独立 conversation/trace/evaluation 数据库；每 run 新 conversation，无 history 污染。固定 seed 的 AB/BA counterbalance。HTTP event hooks 只观测原 client 序列化请求与公开 response 字段，不修改请求；stream 字节原样传递，usage/finish/visible output 单独保存，隐藏 reasoning 正文不落盘。现有 max_retries=0。

源码、8 个 bundle、runner 在第一次请求前做逐字副本并逐字对比。执行 commit + dirty state + git diff + 冻结副本共同记录代码身份，不使用哈希。结果/文档是执行后派生产物，不属于冻结源码。

自动指标复用 build_case_ground_truth/evaluate_end_to_end_case，语义正确性与 citation entailment 由独立 blind reviewer 检查；不把 provenance valid 当事实支持正确。ranking 的固定 GT 只有单一最高值，不能证明真实 tie 场景。
