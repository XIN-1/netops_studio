"""QApplication 封装（app/application.py）。

职责：
- 作为全局唯一 QApplication 子类（进程内通常仅实例化一次，扮演「单例」角色）。
- 通过重写 notify() 提供全局异常兜底，避免单个槽函数 / 事件处理抛错导致整个
  应用崩溃退出。
- 提供 qt_message_handler 静态方法，集中捕获 Qt 内部日志（警告 / 致命错误）。

对应开发文档 §4（程序入口与应用生命周期）。
"""

from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox


class NetOpsApplication(QApplication):
    """应用主对象。在 main.py 中以 `NetOpsApplication(sys.argv)` 创建，
    并作为 Qt 事件循环（app.exec()）的宿主。"""

    def __init__(self, argv) -> None:
        super().__init__(argv)
        # 记录最近一次被全局异常兜底层捕获的错误信息，便于外部排查。
        self._last_error: str = ""

    @staticmethod
    def qt_message_handler(mode, context, message) -> None:
        # 统一捕获 Qt 内部警告/错误，便于排查（不弹窗，避免刷屏）。
        # 注意：本处理器需在程序启动时通过
        #   QtCore.qInstallMessageHandler(NetOpsApplication.qt_message_handler)
        # 显式安装后才会生效；当前 main.py 并未安装，故它目前不会被调用。
        if mode == 4:  # QtFatalMsg
            print(f"[Qt FATAL] {message} ({context.file}:{context.line})")

    def notify(self, receiver, event):  # type: ignore[override]
        # 全局异常兜底，避免单点崩溃导致整个应用退出。
        # notify 是 Qt 派发所有事件的最后一道关口，任意事件的 handler 抛出的
        # 未捕获异常都会冒泡到这里；捕获后仅打印并丢弃，返回 False 表示事件未
        # 被「成功处理」（但不影响后续事件继续派发）。
        try:
            return super().notify(receiver, event)
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            print("[Uncaught]", traceback.format_exc())
            return False
