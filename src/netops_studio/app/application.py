"""QApplication 封装（app/application.py）。

单例、全局异常处理。参考文档 §4。
"""

from __future__ import annotations

import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox


class NetOpsApplication(QApplication):
    def __init__(self, argv) -> None:
        super().__init__(argv)
        self._last_error: str = ""

    @staticmethod
    def qt_message_handler(mode, context, message) -> None:
        # 统一捕获 Qt 内部警告/错误，便于排查（不弹窗，避免刷屏）
        if mode == 4:  # QtFatalMsg
            print(f"[Qt FATAL] {message} ({context.file}:{context.line})")

    def notify(self, receiver, event):  # type: ignore[override]
        # 全局异常兜底，避免单点崩溃导致整个应用退出
        try:
            return super().notify(receiver, event)
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            print("[Uncaught]", traceback.format_exc())
            return False
