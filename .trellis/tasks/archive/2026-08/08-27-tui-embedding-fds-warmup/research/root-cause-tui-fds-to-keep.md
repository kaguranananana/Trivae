# 根因研究：Textual TUI 下 SEMANTIC_EMBEDDING_FAILED（bad value(s) in fds_to_keep）

日期：2026-08-27　|　状态：已实测复现并闭环验证

## 触发链（完整）

1. Textual `App` 启动时把 `sys.stdout` / `sys.stderr` 替换为 `textual.app._PrintCapture`
   （`app.py:731-733`），其 `fileno()` **返回 -1**（不抛异常）。实测：
   - 进 App 前：`<_io.TextIOWrapper name='<stderr>' ...>`
   - 进 App 后：`t_stderr = <class 'textual.app._PrintCapture'>`，`fd_stderr = -1`
2. `semantic_search` 首次懒加载 `Qwen/Qwen3-Embedding-0.6B`（`src/trivae/retrieval/semantic/embedding.py::_load_model`）。
3. sentence-transformers 加载权重时打印 tqdm 进度条；`tqdm.std.TqdmDefaultWriteLock.__init__`
   （site-packages/tqdm/std.py ~L93）调用 `cls.create_mp_lock()` 惰性创建 `multiprocessing.RLock()`。
4. 创建 POSIX 信号量需要向 `multiprocessing.resource_tracker` 注册（首次会启动 tracker 子进程）。
5. CPython 3.14 `Lib/multiprocessing/resource_tracker.py::_launch()`（~L238）：
   ```python
   fds_to_pass = []
   try:
       fds_to_pass.append(sys.stderr.fileno())   # 只防异常，不防空值！Textual 下拿到 -1
   except Exception:
       pass
   r, w = os.pipe()
   ...
   pid = util.spawnv_passfds(exe, args, fds_to_pass)
   ```
6. `multiprocessing.util.spawnv_passfds` → `_posixsubprocess.fork_exec(...)` 校验 fd 合法性，
   收到 `[‑1, 10]` → `ValueError: bad value(s) in fds_to_keep`。
7. 异常在 `embedding.py:_load_model` 被包装为 `SemanticEmbeddingError`
   （error_code=`SEMANTIC_EMBEDDING_FAILED`）。

## 实测对照数据（插桩 spawnv_passfds）

| 运行环境 | fds_to_pass | 结果 |
| --- | --- | --- |
| 纯 asyncio + 相同 provider preload | `[2, 10]` | 成功 |
| Textual headless（run_test）+ 同样 preload | `[-1, 10]` | ValueError |

两种环境的 `SC_OPEN_MAX=1048575`、rlimit、打开 fd 集合完全一致——差异只有 stderr 替身。

## 时间线证据

- `ebbc457 08-27 02:03 feat(interfaces): add Textual TUI projection`：TUI 引入。
- trace 统计（data/traces/*.log，按 `SEMANTIC_EMBEDDING_FAILED` 计数）：
  - 08-24 22:00 ～ 08-27 01:00：sem_ok>0、emb_fail=0（CLI 时代全部正常）
  - 08-27 01:56、01:58、02:00 起：emb_fail≥2 的 trace 连续出现至今（TUI 联调与使用时段）
  - CLI `--plain` 从未出现该失败
- 用户失败 trace：`data/traces/trace-57e84f0e5b18434fb444aa0f377c2be1.log`
  （tool result 含根因 message，系 Session 38 错误透传修复生效后的产物）

## 关键结论 / 方案依据

- 单独导入 textual / 纯 asyncio loop 中加载模型均**不复现**；必须处于真实 App runtime
  （stdio 已被 `_PrintCapture` 替换）才触发。headless run_test 可稳定复现 ⇒ 可做确定性测试。
- 修复点选在本仓库可管辖的边界：`TrivaeChatApp.run()` **之前**（application 已构造完成，
  stdio 仍真实，见 `cli.py:1474→1478` 的执行顺序）预热 tqdm mp lock，
  使 `_PrintCapture` 出现前一次性副作用（信号量 + tracker 启动）已完成。
- 上游缺陷对应：CPython gh Issue(resource_tracker 未校验 fileno 值) × textual
  `_PrintCapture.fileno() == -1`。两者都不可在本仓库修改，故采用"提前消除触发条件"方案。

## 复现脚本存档

诊断用脚本位于系统临时目录（会话内有效）：`tui_embed_repro.py`、`tui_fd_probe.py`
（/var/folders/ct/c_406rh940z5g1k0nj8vlmrw0000gn/T/opencode/）。核心机制已转述如上，
正式回归测试不依赖这些脚本或任何模型下载。
