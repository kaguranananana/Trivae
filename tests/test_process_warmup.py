"""bootstrap process_warmup 回归测试：Textual 坏 stderr 下 tqdm mp lock 预热。

背景：Textual App 把 ``sys.stderr`` 替换成 ``_PrintCapture``（``fileno()`` 返回 -1），
CPython 3.14 ``resource_tracker._launch()`` 不校验 fd 值就把 -1 传给
``_posixsubprocess.fork_exec``，导致嵌入模型首次加载时 tqdm 惰性建锁抛出
``ValueError: bad value(s) in fds_to_keep``。本文件固化上游失败模式本身与
预热修复的确定性链路，不依赖 torch / sentence-transformers / 网络 / 真实模型。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest import mock

from tqdm.std import TqdmDefaultWriteLock

from trivae.bootstrap import application as application_module
from trivae.bootstrap.application import create_application
from trivae.bootstrap.process_warmup import warm_tqdm_multiprocessing_lock


class _PrintCaptureLikeStderr:
    """模拟 textual.app._PrintCapture 行为：fileno() 返回 -1 而不是抛异常。"""

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        return None

    def fileno(self) -> int:
        return -1


@contextmanager
def _tracker_launch_window() -> Iterator[None]:
    """让下一次共享资源注册强制走 resource_tracker._launch()，结束后完整还原。

    tracker 进程存活期间，后续注册只通过既有管道复用、不会再读取 sys.stderr；
    同一 pytest 进程内必须临时制造"从未启动"状态才能确定性触发 _launch()。
    这里只暂时挪开单例的 ``_fd`` / ``_pid`` 标记，不停止真实的 tracker 子进程，
    其余资源注册关系原样保留；要求单线程执行（pytest 套件满足）。
    依赖 CPython ≥3.13 的 ResourceTracker 单例结构（当前运行时为 3.14.6）。
    """

    from multiprocessing import resource_tracker

    tracker = resource_tracker._resource_tracker
    with tracker._lock:
        saved_fd = tracker._fd
        saved_pid = tracker._pid
        tracker._fd = None
        tracker._pid = None
    try:
        yield
    finally:
        with tracker._lock:
            tracker._fd = saved_fd
            tracker._pid = saved_pid


@unittest.skipUnless(os.name == "posix", "tqdm multiprocessing lock 仅存在于 POSIX fork 平台")
class ProcessWarmupTests(unittest.TestCase):
    """验证 warm_tqdm_multiprocessing_lock 的复现、修复、幂等与接线 contract。"""

    _MP_LOCK_MISSING = object()

    def setUp(self) -> None:
        # 保存并恢复 tqdm 类上的缓存锁属性：每个用例从"无缓存锁"出发，
        # 保证预热与建锁路径真实执行；其它测试也不会看到本文件创建的锁状态。
        self._original_mp_lock = getattr(TqdmDefaultWriteLock, "mp_lock", self._MP_LOCK_MISSING)
        self.addCleanup(self._restore_mp_lock)
        if hasattr(TqdmDefaultWriteLock, "mp_lock"):
            delattr(TqdmDefaultWriteLock, "mp_lock")

    def _restore_mp_lock(self) -> None:
        if self._original_mp_lock is self._MP_LOCK_MISSING:
            if hasattr(TqdmDefaultWriteLock, "mp_lock"):
                delattr(TqdmDefaultWriteLock, "mp_lock")
        else:
            TqdmDefaultWriteLock.mp_lock = self._original_mp_lock

    def test_broken_stderr_direct_lock_creation_raises(self) -> None:
        """复现控制测试：frozen broken stdio 下直接建锁必须抛 ValueError。"""

        with (
            mock.patch("sys.stderr", new=_PrintCaptureLikeStderr()),
            _tracker_launch_window(),
        ):
            with self.assertRaisesRegex(ValueError, r"bad value\(s\) in fds_to_keep"):
                try:
                    # 与生产失败链一致：实例化触发 __init__ 内部的 create_mp_lock，
                    # RLock() 注册信号量 → tracker 冷态走 _launch 读到 fileno()==-1。
                    TqdmDefaultWriteLock()
                finally:
                    # create_mp_lock 抛出发生在 tqdm 把 th_lock 写回之前，
                    # __init__ 已 acquire 的全局线程锁不会自动 release；
                    # 同线程补一次 release 保持配对，避免卡死其它测试。
                    TqdmDefaultWriteLock.th_lock.release()
            # 失败路径不得留下半成品锁缓存。
            self.assertFalse(hasattr(TqdmDefaultWriteLock, "mp_lock"))

    def test_warmup_before_broken_stderr_allows_lock_creation(self) -> None:
        """修复验证：预热发生在 stdio 冻结之前（与生产接线时序一致），随后坏 stderr 下建锁成功。

        生产序列：create_application（stdio 真实）→ 预热 → TrivaeChatApp.run()
        （stdio 被 _PrintCapture 替换）→ 模型加载时 tqdm 建锁命中缓存短路，
        不再触碰 resource_tracker 启动路径。
        """

        # stdio 尚真实：完成预热（真实 RLock 创建会启动 tracker 子进程，macOS 正常行为）。
        warm_tqdm_multiprocessing_lock()
        warmed_lock = getattr(TqdmDefaultWriteLock, "mp_lock")
        self.assertIsNotNone(warmed_lock)

        with mock.patch("sys.stderr", new=_PrintCaptureLikeStderr()):
            lock = TqdmDefaultWriteLock()
            self.assertIn(TqdmDefaultWriteLock.mp_lock, lock.locks)

    def test_warmup_is_idempotent(self) -> None:
        """幂等：连续两次预热返回同一缓存锁对象，无副作用。"""

        warm_tqdm_multiprocessing_lock()
        first = getattr(TqdmDefaultWriteLock, "mp_lock")
        warm_tqdm_multiprocessing_lock()
        second = getattr(TqdmDefaultWriteLock, "mp_lock")
        self.assertIsNotNone(first)
        self.assertIs(first, second)

    def test_create_application_invokes_warmup_once(self) -> None:
        """接线：create_application 构造 Application 时恰好触发一次预热入口。

        该位置在 TrivaeChatApp.run() 替换 stdio 之前，即消除缺陷窗口的正确时点。
        """

        calls: list[int] = []

        def counting_warmup() -> None:
            calls.append(1)

        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "warmup-wiring.sqlite3"
            with (
                mock.patch.object(
                    application_module,
                    "warm_tqdm_multiprocessing_lock",
                    side_effect=counting_warmup,
                ),
                create_application(database_path),
            ):
                pass

        self.assertEqual(calls, [1])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
