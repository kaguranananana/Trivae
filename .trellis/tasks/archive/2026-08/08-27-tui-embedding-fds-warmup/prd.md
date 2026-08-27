# 修复 Textual TUI 下语义检索 SEMANTIC_EMBEDDING_FAILED

## Goal

在 Textual TUI 模式下，`semantic_search` 工具不再因
`ValueError: bad value(s) in fds_to_keep` 导致嵌入模型加载失败；
语义检索恢复到 08-27 01:00（TUI 引入前）的正常可用状态。

## Background / Root Cause（已实测定位）

- 失败链：Textual App 将 `sys.stdout/sys.stderr` 替换为 `_PrintCapture`（其 `fileno()` 返回 `-1` 而非抛异常）
  → 首次懒加载嵌入模型时 tqdm 进度条惰性创建 `multiprocessing.RLock`
  → POSIX 信号量首次启动 `resource_tracker` 子进程
  → CPython 3.14 `resource_tracker._launch()` 把 `sys.stderr.fileno()` 未校验地传入
    `_posixsubprocess.fork_exec` → `ValueError: bad value(s) in fds_to_keep`。
- 实测对照：纯 asyncio 环境 `fds_to_pass=[2, 10]` 成功；Textual 环境下为 `[-1, 10]` 失败。
- 时间线证据：`ebbc457 08-27 02:03 feat(interfaces): add Textual TUI projection` 之后，
  所有走 TUI 的 semantic trace 全部失败（01:56 起至今）；CLI `--plain` 与裸进程一直正常。
- 上游性质：textual 返回非法 fd 与 CPython 不校验 fd 的组合缺陷；本仓库无法改上游，
  但可以在 stdio 尚未被捕获时消除触发该缺陷的进程一次性状态。

## Requirements

- 在 `TrivaeChatApp.run()` 之前（stdio 仍为真实终端）完成 tqdm multiprocessing lock 的
  一次性预热，使后续嵌入模型加载不会走"启动 resource_tracker 时读取已损坏 stderr"的路径。
- 预热必须幂等，可在 CLI（plain/TUI 共用入口）重复调用且零副作用。
- 不降级、不掩错：不吞异常、不加 fallback 分支；若上游依赖缺失则维持既有可选 extra 语义。
- 修复不得改变 CLI plain 路径与 Semantic provider 现有 contract（identity、error_code、
  测试全部不动语义）。

## Acceptance Criteria

- [ ] 新增确定性回归测试：以 `fileno()==-1` 的 stderr 替身复现"frozen broken stdio 下
      直接创建 tqdm lock 会抛 ValueError"，而经预热后同一场景可正常创建锁；测试不依赖
      torch/sentence-transformers/网络/真实模型下载。
- [ ] TUI headless 场景验收：模拟 App runtime 中执行默认构造的 embedding preload 成功
      （或等效确定性链路验证），trace/tool result 不再出现 `SEMANTIC_EMBEDDING_FAILED`。
- [ ] `pytest`、`ruff`、`mypy` 全绿；现有 377+ 测试不回归。
