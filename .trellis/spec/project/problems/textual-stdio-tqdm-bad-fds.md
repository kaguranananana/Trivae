# Textual TUI 下语义检索 SEMANTIC_EMBEDDING_FAILED（bad value(s) in fds_to_keep）

日期：2026-08-27　|　组件：`interfaces/tui` × `bootstrap` × CPython/textual 上游

## Problem

引入 Textual TUI（`ebbc457 feat(interfaces): add Textual TUI projection`）之后，所有
走 TUI 的 Query 里 `semantic_search` 工具都失败：

```
error_code = SEMANTIC_EMBEDDING_FAILED
message    = failed to load embedding model Qwen/Qwen3-Embedding-0.6B:
             ValueError: bad value(s) in fds_to_keep
```

AI 只能降级用 SQL 取最近 N 条消息作答；同机 CLI `--plain` 与裸进程加载完全正常。

## Evidence

- 时间线：08-24 22:00～08-27 01:00 的 trace 全部正常（sem_ok>0、emb_fail=0）；
  01:56 起所有 emb_fail≥2 的失败 trace 都在 TUI 时段，与 TUI 提交时间吻合。
- 失败 trace `data/traces/trace-57e84f0e5b18434fb444aa0f377c2be1.log` 的 tool result
  已含根因 message（Session 38 错误透传修复的成果），可直接读出 ValueError 文本。
- 对照插桩（hook `multiprocessing.util.spawnv_passfds` 打印参数并 fstat 每个 fd）：
  - 纯 asyncio 加载同一模型：`fds_to_pass=[2, 10]` → 成功
  - Textual headless 同样操作：`fds_to_pass=[-1, 10]` → fd `-1` invalid，
    `ValueError: bad value(s) in fds_to_keep`
- 环境对照：单独 import textual、纯 asyncio loop、worker thread 均不复现；
  只有真实 App runtime（stdio 已被替换）才触发。

## Root Cause

三层组合缺陷，触发窗口是"进程内第一次启动 resource_tracker 子进程"：

1. textual `App` 把 `sys.stdout/sys.stderr` 替换为 `_PrintCapture`
   （site-packages/textual/app.py:731-733），其 `fileno()` **返回 -1** 而非抛异常。
2. CPython 3.14 `multiprocessing/resource_tracker.py::_launch()` 只用 try/except 防止
   `fileno()` 抛异常，**不校验返回值**，把 -1 直接放进 `fds_to_pass`。
3. trivae 侧：嵌入模型懒加载时 sentence-transformers 的 tqdm 进度条首次执行
   `TqdmDefaultWriteLock.create_mp_lock()` → `multiprocessing.RLock()` → POSIX 信号量
   注册 → 恰好落进上述窗口。

## Options

1. 在 Application 构造期（stdio 尚真实）预热 tqdm mp lock，提前完成一次性副作用。
2. monkeypatch textual `_PrintCapture.fileno()` 抛异常——全局篡改第三方运行时行为。
3. 设置 `TQDM_DISABLE=1` 关闭进度条——丢掉合法 UX，属于降级掩盖。
4. 改用进程隔离跑模型加载——架构级重构，成本与收益不成比例。

## Decision

选方案 1：新增 `src/trivae/bootstrap/process_warmup.py::warm_tqdm_multiprocessing_lock()`，
在 `create_application()` 工厂最早期调用（此时 `TrivaeChatApp.run()` 尚未替换 stdio）。

## Why

- 命中"本仓库可管辖边界上的最小修复"：不改上游、不吞错、无 fallback 分支；
  预热只把"必然要发生的锁创建"提前到安全时点，后续模型加载短路命中缓存。
- 幂等且零行为变化：CLI plain / eval / semantic 等共用工厂的路径同样受益，
  无锁可建（未装 `[semantic]` extra）时按可选依赖 contract 直接返回。

## Result

- pytest 377→381 全绿；ruff、mypy 通过。
- 测试突变复验：移除接线 → 接线测试红；预热改 no-op → 修复验证测试红。
- TUI 下语义检索恢复到 TUI 引入前的可用状态（headless 复现链路确定性消除）。

## Trade-off

- 回归测试依赖 CPython ≥3.13 `ResourceTracker` 单例私有结构制造冷态窗口
  （有版本注释与 POSIX skipUnless 保护）；CPython 内部结构变化时该测试会显式失败。
- 若未来有其它库在 TUI runtime 内首次创建 POSIX 信号量，仍会踩中同样的上游缺陷窗口；
  本修复只覆盖已知当事人 tqdm（即当前依赖树中唯一的触发点）。

## Regression

- `tests/test_process_warmup.py`：
  - 复现控制测试固化上游失败模式本身（坏 stderr + tracker 冷态直接建锁抛 ValueError）；
  - 修复验证测试锁定生产时序（预热 → stdio 冻结 → 建锁成功）；
  - 幂等测试与 `create_application` 接线测试防止回归回退。
- 完整实测证据存档：任务目录
  `.trellis/tasks/08-27-tui-embedding-fds-warmup/research/root-cause-tui-fds-to-keep.md`。
