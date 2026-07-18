"""协作式异步工作器（app/async_worker.py）。

设计目标：把「耗时业务」放到 QThreadPool 的 worker 线程里执行，执行期间通过
Qt 信号把进度 / 结果回传主线程 UI，并支持「取消」。对应开发文档 §7。

为什么不用线程强杀：Python 没有提供安全的 `Thread.terminate`，强行杀线程会留下
锁、partially-initialized 状态等隐患。因此采用**协作式取消**——job 内部在循环 /
IO 等检查点轮询 `should_stop()`，外部调用 `request_stop()` 仅设置一个
`threading.Event`，真正退出由 job 自己决定（见下方注释）。

跨线程上报机制：WorkerSignals 是 QObject，其 Signal 在「发射线程 ≠ 接收对象所在
线程」时由 Qt 自动以 Qt.QueuedConnection 入队，经由接收方事件循环安全回调——即
便本模块没有手写 QMetaObject.invokeMethod，信号本身已具备跨线程排队能力。
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from PySide6.QtCore import QRunnable, QThreadPool, Signal, QObject, Slot


class WorkerSignals(QObject):
    """每个 JobBase 持有一个独立的 signal 集合，用于跨线程上报状态。

    由于它继承自 QObject，信号可在 worker 线程发射、在主线程的槽中安全接收。
    """

    started = Signal()
    progress = Signal(int, int)            # done, total
    result = Signal(object)
    finished = Signal()
    error = Signal(str)


class JobBase(QRunnable):
    """业务任务基类：子类实现 run_job()，并在检查点调用 should_stop() 协作取消。"""

    def __init__(self) -> None:
        super().__init__()
        # 局部导入 Event 仅为就近说明；它即标准库 threading.Event（协作取消标志位）。
        from threading import Event

        # 每个 job 独占一份 signals（非共享），避免多个 job 的信号互相干扰。
        self.signals = WorkerSignals()
        # 协作式取消标志：request_stop() 置位，should_stop() 读取。
        self._stop = Event()
        # 预留的自动删除开关；QRunnable 默认在 run() 结束后自动析构，本字段当前未被读取。
        self._auto_delete = True

    def should_stop(self) -> bool:
        # 轮询入口：job 在循环 / 分段处理中频繁调用它判断是否该退出。
        return self._stop.is_set()

    def request_stop(self) -> None:
        # 外部（如 UI 的「停止」按钮）调用，仅置位 Event，不强制中断线程。
        self._stop.set()

    def run(self) -> None:  # QRunnable 入口（由 QThreadPool 在线程中调用）
        # 统一流程：先发 started -> 执行 run_job -> 无论成败都发 finished。
        self.signals.started.emit()
        try:
            self.run_job()
        except Exception as exc:  # noqa: BLE001
            # 任何未捕获异常都转成 error 信号上报给主线程（异常不在线程间直接抛出），
            # 由 on_error 回调处理，而不是让 worker 线程带着异常静默结束。
            self.signals.error.emit(str(exc))
        finally:
            # 即使 run_job 抛错也保证 finished 被发射，便于 UI 复位「运行中」状态。
            self.signals.finished.emit()

    def run_job(self) -> None:  # 子类实现
        # 约定：子类在此编写业务逻辑，并在合适检查点调用 self.should_stop() 提前返回，
        # 以实现协作式取消。未实现则运行时抛 NotImplementedError。
        raise NotImplementedError


class AsyncWorker:
    """线程池封装，管理 JobBase 的提交、回调绑定与协作取消。"""

    def __init__(self) -> None:
        # 复用进程级全局线程池（按需自动扩容，执行完回收线程）。
        self._pool = QThreadPool.globalInstance()
        # 仅保留「最近一次」提交的 job 引用，用于 cancel() 取消（见 cancel 说明）。
        self._current: Optional[JobBase] = None

    def submit(self, job: JobBase,
               on_result: Optional[Callable[[Any], None]] = None,
               on_progress: Optional[Callable[[int, int], None]] = None,
               on_finished: Optional[Callable[[], None]] = None,
               on_error: Optional[Callable[[str], None]] = None) -> None:
        # 在 start 之前绑定回调：信号与槽的连接必须在发射前完成，
        # 否则可能丢失 started / 早期 progress。
        if on_result:
            job.signals.result.connect(on_result)
        if on_progress:
            job.signals.progress.connect(on_progress)
        if on_finished:
            job.signals.finished.connect(on_finished)
        if on_error:
            job.signals.error.connect(on_error)
        # 覆盖为当前 job（注意：若上一个 job 仍在运行，其引用将被替换而「丢失」，
        # 之后 cancel() 只能取消最新提交的 job）。
        self._current = job
        # 交由线程池调度，run() 将在某条 worker 线程中异步执行。
        self._pool.start(job)

    def cancel(self) -> None:
        # 仅对「最近一次」提交的 job 请求取消。若需同时管理多个并发 job，
        # 应改为按 key 维护 job 集合（当前设计偏向「同一时刻单任务」场景）。
        if self._current:
            self._current.request_stop()

    def is_running(self) -> bool:
        # 注意：返回的是「全局线程池」的活跃线程数，而非本 worker 当前 job 的状态；
        # 只要进程内任何地方占用了该全局池的线程，这里都会返回 True。如要精确判断
        # 当前 job 是否还在跑，应跟踪 self._current 是否已收到 finished 信号。
        return self._pool.activeThreadCount() > 0
