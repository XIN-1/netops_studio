"""主窗口（gui/shell/main_window.py）。

左侧导航（品牌头部 + 分组列表）+ 右侧堆叠工作区 + 状态栏 + 顶部工具栏（主题切换）。
每个模块被自动包裹进带统一内边距的 ScrollBox，使全部 Tab 一致可滚、留白统一。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QStackedWidget, QStatusBar,
    QToolBar, QWidget,
)

from ...app import Theme, tr
from ...app.tab_registry import TabRegistry
from ..widgets import ScrollBox


class MainWindow(QMainWindow):
    def __init__(self, registry: TabRegistry, theme: Theme) -> None:
        super().__init__()
        self.registry = registry
        self.theme = theme
        self._pages: dict[str, QWidget] = {}
        self.setWindowTitle(tr("app.title"))
        self.resize(1180, 760)

        # 导航面板
        from .nav_panel import NavPanel

        self.nav = NavPanel(registry, self._select)

        # 侧边栏外壳（带背景与右分隔线）
        self.sidebar = QWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(248)
        sb_lay = QHBoxLayout(self.sidebar)
        sb_lay.setContentsMargins(0, 0, 0, 0)
        sb_lay.addWidget(self.nav, 1)

        self._setup_ui()

        # 状态栏
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage(tr("status.ready"))

        # 工具栏（主题切换）
        self._build_toolbar()

        # 应用主题
        self._apply_theme()

    def _setup_ui(self) -> None:
        central = QWidget()
        lay = QHBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.stack = QStackedWidget()
        lay.addWidget(self.sidebar, 0)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

    def _build_toolbar(self) -> None:
        tb = QToolBar("main")
        tb.setMovable(False)
        self.addToolBar(tb)
        self.theme_btn = tb.addAction("🌓 主题")
        self.theme_btn.setToolTip("切换浅色 / 深色主题")
        self.theme_btn.triggered.connect(self._toggle_theme)

    def _select(self, tab_id: str) -> None:
        desc = self.registry.get(tab_id)
        if desc is None or not desc.enabled or desc.factory is None:
            self.status.showMessage(f"{tab_id} 尚未开放")
            return
        if tab_id not in self._pages:
            widget = desc.build()
            if widget is None:
                return
            self._pages[tab_id] = ScrollBox(widget)
        page = self._pages[tab_id]
        idx = self.stack.indexOf(page)
        if idx == -1:
            self.stack.addWidget(page)
            idx = self.stack.indexOf(page)
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
