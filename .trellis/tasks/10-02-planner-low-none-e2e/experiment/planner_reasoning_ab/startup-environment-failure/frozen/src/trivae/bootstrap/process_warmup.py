"""进程级一次性副作用预热：在 stdio 被 TUI runtime 接管前消除上游缺陷触发窗口。"""

from __future__ import annotations


def warm_tqdm_multiprocessing_lock() -> None:
    """提前创建 tqdm multiprocessing lock，修复 Textual TUI 下嵌入模型加载失败。

    触发条件与根因（完整实测证据见
    `.trellis/tasks/08-27-tui-embedding-fds-warmup/research/root-cause-tui-fds-to-keep.md`）：

    - Textual ``App`` 启动时把 ``sys.stdout`` / ``sys.stderr`` 替换为
      ``textual.app._PrintCapture``，其 ``fileno()`` 返回 ``-1`` 而不是抛异常。
    - 首次懒加载 sentence-transformers 嵌入模型时，tqdm 进度条惰性执行
      ``TqdmDefaultWriteLock.create_mp_lock()`` 创建 ``multiprocessing.RLock()``；
      POSIX 信号量需要向 ``multiprocessing.resource_tracker`` 注册，
      首次注册会启动 tracker 子进程。
    - CPython 3.14 ``resource_tracker._launch()`` 不校验 ``sys.stderr.fileno()``
      的返回值，把 ``-1`` 一并传给 ``_posixsubprocess.fork_exec``，
      抛出 ``ValueError: bad value(s) in fds_to_keep``，最终被包装成
      ``SEMANTIC_EMBEDDING_FAILED``。

    因此必须在 stdio 尚为真实终端的阶段（``create_application`` 构造期、
    ``TrivaeChatApp.run()`` 替换 stdio 之前）完成这次进程级一次性副作用：
    提前缓存锁并启动 resource_tracker 之后，模型加载路径上的 tqdm 建锁
    直接命中 ``hasattr(cls, "mp_lock")`` 短路，不再触碰该缺陷窗口。

    边界说明：

    - 幂等：``create_mp_lock`` 自带 ``hasattr`` 判断，重复调用零副作用。
    - ``ImportError`` 时直接返回：tqdm 是 pyproject 可选 extra ``[semantic]``
      （经 sentence-transformers 传入）的依赖；缺依赖是受支持的合法形态，
      语义检索入口自身会在真正使用时暴露 ImportError——这里只是不预热，
      不是吞错降级。
    - 除上述 ImportError 外不允许捕获任何异常：建锁失败必须显式暴露。
    """
    try:
        # 局部 import 与 embedding.py 的可选重量延迟导入惯例一致。
        from tqdm.std import TqdmDefaultWriteLock
    except ImportError:
        return
    TqdmDefaultWriteLock.create_mp_lock()
