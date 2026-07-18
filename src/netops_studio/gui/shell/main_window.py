"""主窗口（gui/shell/main_window.py）。

左侧导航 + 右侧堆叠工作区 + 状态栏 + 顶部工具栏（主题切换）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QStackedWidget, QStatusBar, QToolBar, QWidget,
)

from ...app import Theme, tr
from ...app.tab_registry import TabRegistry


class MainWindow(QMainWindow):
    def __init__(self, registry: TabRegistry, theme: Theme) -> None:
        super().__init__()
        self.registry = registry
        self.theme = theme
        self.setWindowTitle(tr("app.title"))
        self.resize(1100, 720)

        # 导航面板
        from .nav_panel import NavPanel

        self.nav = NavPanel(registry, self._select)
        self._setup_ui()

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(tr("status.ready"))

        # 工具栏
        self._build_toolbar()

        # 应用主题
        self._apply_theme()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QWidget

        central = QWidget()
        lay = QHBoxLayout(central)
        self.stack = QStackedWidget()
        lay.addWidget(self.nav, 1)
        lay.addWidget(self.stack, 4)
        self.setCentralWidget(central)

    def _build_toolbar(self) -> None:
        tb = QToolBar("main")
        self.addToolBar(tb)
        self.theme_btn = tb.addAction("🌓 主题")
        self.theme_btn.triggered.connect(self._toggle_theme)

    def _select(self, tab_id: str) -> None:
        desc = self.registry.get(tab_id)
        if desc is None or not desc.enabled or desc.factory is None:
            self.status.showMessage(f"{tab_id} 尚未开放")
            return
        widget = desc.build()
        if widget is None:
            return
        idx = self.stack.indexOf(widget)
        if idx == -1:
            self.stack.addWidget(widget)
            idx = self.stack.indexOf(widget)
        self.stack.setCurrentIndex(idx)
        self.status.showMessage(desc.title)

    def _toggle_theme(self) -> None:
        new_mode = "dark" if self.theme.token.name == "light" else "light"
        self.theme.set_mode(new_mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self.theme.qss())
