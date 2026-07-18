"""主窗口（gui/shell/main_window.py）。

骨架：左侧导航（品牌头部 + 分组列表）+ 右侧堆叠工作区 + 状态栏 + 顶部工具栏（主题切换）。
每个模块被自动包裹进带统一内边距的 ScrollBox，使全部 Tab 一致可滚、留白统一。

Tab 采用「懒加载 + 单例缓存」：首次 _select 才经 TabRegistry 构造 widget，并包成
ScrollBox 缓存到 self._pages；之后切换只切换堆叠页，不重复构造、不丢状态。
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
    """应用主窗口：组装侧栏、堆叠工作区、状态栏与工具栏，并负责主题刷新。"""

    def __init__(self, registry: TabRegistry, theme: Theme) -> None:
        super().__init__()
        self.registry = registry
        self.theme = theme
        # tab_id -> 已包裹 ScrollBox 的页面（懒加载单例缓存）。
        self._pages: dict[str, QWidget] = {}
        self.setWindowTitle(tr("app.title"))
        self.resize(1180, 760)

        # 导航面板（局部导入避免与主模块循环依赖；NavPanel 仅依赖 registry 与回调）。
        from .nav_panel import NavPanel

        self.nav = NavPanel(registry, self._select)

        # 侧边栏外壳（带背景与右分隔线，锚定 theme 的 QWidget#Sidebar 样式）。
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
        # 侧栏固定宽（0 权重），堆叠工作区占满剩余空间（1 权重）。
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
        # 守卫：未注册的、被禁用或尚未提供 factory 的 Tab 一律视为「尚未开放」。
        desc = self.registry.get(tab_id)
        if desc is None or not desc.enabled or desc.factory is None:
            self.status.showMessage(f"{tab_id} 尚未开放")
            return
        # 懒加载 + 单例缓存：首次才构造并包裹 ScrollBox；之后复用同一页。
        if tab_id not in self._pages:
            widget = desc.build()
            if widget is None:
                return
            self._pages[tab_id] = ScrollBox(widget)
        page = self._pages[tab_id]
        # QStackedWidget 不自动去重：先查是否已加入，未加入则 addWidget 后再取索引。
        idx = self.stack.indexOf(page)
        if idx == -1:
            self.stack.addWidget(page)
            idx = self.stack.indexOf(page)
        self.stack.setCurrentIndex(idx)
        self.status.showMessage(desc.title)

    def _toggle_theme(self) -> None:
        # 在 light/dark 间来回切换，再刷新全局 QSS。
        new_mode = "dark" if self.theme.token.name == "light" else "light"
        self.theme.set_mode(new_mode)
        self._apply_theme()

    def _apply_theme(self) -> None:
        # 把当前主题的 QSS 设为「全局样式表」，对全部 widget 生效（含已构造与后续构造的）。
        # 若将来某些页面在切换主题前已构造且含内联 styleSheet，需在其自身刷新以覆盖。
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self.theme.qss())
