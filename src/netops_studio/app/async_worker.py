"""协作式异步工作器（app/async_worker.py）。

QRunnable + threading.Event 协作停止。禁用线程强杀（Thread.terminate）。
信号 started / progress / finished / error。参考文档 §7。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QRunnable, QThreadPool, Signal, QObject, Slot


class WorkerSignals(QObject):
    started = Signal()
    progress = Signal(int, int)            # done, total
    result = Signal(object)
    finished = Signal()
    error = Signal(str)


class JobBase(QRunnable):
    """业务任务基类：实现 run_job，并在检查点调用 should_stop() 协作取消。"""

    def __init__(self) -> None:
        super().__init__()
        from threading import Event

        self.signals = WorkerSignals()
        self._stop = Event()
        self._auto_delete = True

    def should_stop(self) -> bool:
        return self._stop.is_set()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # QRunnable 入口
        self.signals.started.emit()
        try:
            self.run_job()
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()

    def run_job(self) -> None:  # 子类实现
        raise NotImplementedError


class AsyncWorker:
    """线程池封装，管理 JobBase 生命周期与协作取消。"""

    def __init__(self) -> None:
        self._pool = QThreadPool.globalInstance()
        self._current: Optional[JobBase] = None

    def submit(self, job: JobBase,
               on_result: Optional[Callable[[Any], None]] = None,
               on_progress: Optional[Callable[[int, int], None]] = None,
               on_finished: Optional[Callable[[], None]] = None,
               on_error: Optional[Callable[[str], None]] = None) -> None:
        if on_result:
            job.signals.result.connect(on_result)
        if on_progress:
            job.signals.progress.connect(on_progress)
        if on_finished:
            job.signals.finished.connect(on_finished)
        if on_error:
            job.signals.error.connect(on_error)
        self._current = job
        self._pool.start(job)

    def cancel(self) -> None:
        if self._current:
            self._current.request_stop()

    def is_running(self) -> bool:
        return self._pool.activeThreadCount() > 0
