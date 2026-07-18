"""主题与样式（app/theme.py）。

light/dark 设计 token + 现代 QSS 渲染。纯 Python（仅拼装 QSS 字符串，不实例化 Qt 对象）。
设计语言：扁平化工作台风格 —— 圆角卡片、克制的层次、统一的间距与强调色、深浅双主题。

对应开发文档 §7。

QSS 选择器约定（各模块需遵循，方能套用样式）：
- 容器/外壳用 objectName 锚定：QWidget#Sidebar（左侧栏外壳）、
  QListWidget#NavList（侧边导航列表）。
- 语义化「角色」用 property 锚定（在代码里 setProperty("role", ...)）：
  QLabel[role="title"|"subtitle"|"section"|"muted"|"metric"] 用于不同层级文字；
  QFrame[role="card"|"card-accent"] 用于卡片容器；
  QPushButton[role="ghost"|"danger"] 用于次级/危险按钮。
- 导航项的「阶段小标题」复用 NavList::item:disabled 样式（禁用态被刻意用作分组标题），
  因此分组标题项需 setFlags(~ItemIsEnabled)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThemeToken:
    name: str
    bg: str               # 应用背景（最底层）
    surface: str          # 卡片 / 输入控件表面
    surface_hover: str    # 列表 / 按钮 hover 表面
    fg: str               # 主文字
    fg_muted: str         # 次要文字
    accent: str           # 强调色
    accent_hover: str     # 强调色 hover
    accent_pressed: str   # 强调色 按下
    accent_soft: str      # 强调色淡背景（选中/高亮）
    on_accent: str        # 强调色上的文字
    border: str           # 描边
    success: str
    danger: str
    warning: str


LIGHT = ThemeToken(
    name="light",
    bg="#f5f7fb", surface="#ffffff", surface_hover="#eef2f8",
    fg="#1f2430", fg_muted="#6b7280",
    accent="#3b6ef6", accent_hover="#2f5fe0", accent_pressed="#2952c8",
    accent_soft="#eaf1ff", on_accent="#ffffff",
    border="#e4e8f0",
    success="#16a34a", danger="#ef4444", warning="#f59e0b",
)

DARK = ThemeToken(
    name="dark",
    bg="#14161b", surface="#1d2128", surface_hover="#262b34",
    fg="#e6e9ef", fg_muted="#8b93a1",
    accent="#5b8cff", accent_hover="#6f9bff", accent_pressed="#4a78e6",
    accent_soft="#1c2742", on_accent="#0b0d10",
    border="#2b303a",
    success="#22c55e", danger="#f87171", warning="#fbbf24",
)


class Theme:
    """双主题管理：持有当前 ThemeToken 并据此拼装全局 QSS 字符串。"""

    def __init__(self, mode: str = "light") -> None:
        # mode 非 "light" 即视为 dark（容错默认）。LIGHT/DARK 为模块级单例 token。
        self.token = LIGHT if mode == "light" else DARK

    def set_mode(self, mode: str) -> None:
        # 运行时切换主题：仅替换 token 引用，下次调用 qss() 即得到新主题样式。
        self.token = LIGHT if mode == "light" else DARK

    # ------------------------------------------------------------------
    # QSS
    # ------------------------------------------------------------------
    def qss(self) -> str:
        # 以当前 token 的字段（bg/surface/accent/...）插值生成完整样式表字符串。
        # 返回结果直接交给 QApplication.setStyleSheet(...) 全局生效（见 MainWindow._apply_theme）。
        # 注意：此处仅拼装字符串，不创建任何 Qt 对象，故可在任意线程安全调用。
        t = self.token
        t = self.token
        return f"""
        /* ===== 基础 ===== */
        QWidget {{
            background-color: {t.bg};
            color: {t.fg};
            font-family: "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif;
            font-size: 13px;
            selection-background-color: {t.accent_soft};
            selection-color: {t.fg};
        }}
        QAbstractScrollArea {{ border: none; }}

        /* ===== 侧边栏外壳 ===== */
        QWidget#Sidebar {{
            background-color: {t.surface};
            border-right: 1px solid {t.border};
        }}

        /* ===== 文字角色 ===== */
        QLabel[role="title"] {{
            font-size: 20px; font-weight: 700; color: {t.fg};
        }}
        QLabel[role="subtitle"] {{
            font-size: 13px; color: {t.fg_muted};
        }}
        QLabel[role="section"] {{
            font-size: 12px; font-weight: 700; color: {t.fg_muted};
            padding: 2px 0 6px 0;
        }}
        QLabel[role="muted"] {{ color: {t.fg_muted}; }}
        QLabel[role="metric"] {{
            font-size: 26px; font-weight: 700; color: {t.fg};
        }}

        /* ===== 卡片 ===== */
        QFrame[role="card"] {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 12px;
        }}
        QFrame[role="card-accent"] {{
            background-color: {t.accent_soft};
            border: 1px solid {t.accent};
            border-radius: 12px;
        }}

        /* ===== 按钮 ===== */
        QPushButton {{
            background-color: {t.accent};
            color: {t.on_accent};
            border: none;
            border-radius: 8px;
            padding: 8px 16px;
            font-weight: 600;
        }}
        QPushButton:hover {{ background-color: {t.accent_hover}; }}
        QPushButton:pressed {{ background-color: {t.accent_pressed}; }}
        QPushButton:disabled {{
            background-color: {t.surface_hover};
            color: {t.fg_muted};
        }}
        QPushButton[role="primary"] {{
            background-color: {t.accent};
            color: {t.on_accent};
        }}
        QPushButton[role="primary"]:hover {{ background-color: {t.accent_hover}; }}
        QPushButton[role="primary"]:pressed {{ background-color: {t.accent_pressed}; }}
        QPushButton[role="primary"]:disabled {{
            background-color: {t.surface_hover};
            color: {t.fg_muted};
        }}
        QPushButton[role="ghost"] {{
            background-color: transparent;
            color: {t.fg};
            border: 1px solid {t.border};
        }}
        QPushButton[role="ghost"]:hover {{
            background-color: {t.surface_hover};
            border-color: {t.accent};
        }}
        QPushButton[role="danger"] {{
            background-color: {t.danger};
            color: #ffffff;
        }}
        QPushButton[role="danger"]:hover {{ background-color: {t.danger}; opacity: 0.88; }}

        /* ===== 输入控件 ===== */
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 7px 10px;
            color: {t.fg};
        }}
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
        QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
            border: 1px solid {t.accent};
        }}
        QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {{
            color: {t.fg_muted};
            background-color: {t.surface_hover};
        }}
        QComboBox::drop-down {{ border: none; width: 18px; }}
        QComboBox QAbstractItemView {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 8px;
            selection-background-color: {t.accent_soft};
            padding: 4px;
        }}

        /* ===== 表格 / 列表 ===== */
        QTableView, QTreeView, QListWidget {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 10px;
            gridline-color: {t.border};
            outline: 0;
        }}
        QHeaderView::section {{
            background-color: {t.surface_hover};
            color: {t.fg_muted};
            border: none;
            border-bottom: 1px solid {t.border};
            padding: 8px 10px;
            font-weight: 600;
        }}
        QTableWidget::item, QListWidget::item {{
            padding: 7px 10px;
            border: none;
        }}
        QTableView::item:selected, QListWidget::item:selected {{
            background-color: {t.accent_soft};
            color: {t.accent};
        }}

        /* ===== 导航列表（侧边栏） ===== */
        QListWidget#NavList {{
            background: transparent;
            border: none;
            padding: 6px;
            outline: 0;
        }}
        QListWidget#NavList::item {{
            padding: 10px 12px;
            border-radius: 9px;
            color: {t.fg};
            border: none;
        }}
        QListWidget#NavList::item:hover {{
            background-color: {t.surface_hover};
        }}
        QListWidget#NavList::item:selected {{
            background-color: {t.accent_soft};
            color: {t.accent};
            font-weight: 700;
            border-left: 3px solid {t.accent};
            padding-left: 9px;
        }}
        QListWidget#NavList::item:disabled {{
            color: {t.fg_muted};
            padding-top: 16px;
            padding-bottom: 5px;
            font-size: 11px;
            font-weight: 700;
        }}

        /* ===== 分组框（卡片化） ===== */
        QGroupBox {{
            background-color: {t.surface};
            border: 1px solid {t.border};
            border-radius: 12px;
            margin-top: 14px;
            padding: 14px 14px 12px 14px;
            font-weight: 700;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 6px;
            color: {t.fg};
        }}

        /* ===== 标签页 ===== */
        QTabWidget::pane {{
            border: 1px solid {t.border};
            border-radius: 10px;
            top: 0;
        }}
        QTabBar::tab {{
            background: {t.surface_hover};
            color: {t.fg_muted};
            border: 1px solid {t.border};
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            padding: 8px 16px;
            margin-right: 4px;
        }}
        QTabBar::tab:selected {{
            background: {t.surface};
            color: {t.accent};
            font-weight: 700;
            border-color: {t.border};
        }}

        /* ===== 复选框 / 单选 ===== */
        QCheckBox, QRadioButton {{
            spacing: 8px;
            padding: 4px 2px;
        }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 16px; height: 16px;
            border: 1px solid {t.border};
            border-radius: 4px;
            background: {t.surface};
        }}
        QCheckBox::indicator:checked {{
            background: {t.accent};
            border-color: {t.accent};
            image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxMiIgaGVpZ2h0PSIxMiI+PHBhdGggZD0iTTEwIDNsLTEgMUw0LjUgOS41IDIgNy41bC0xIDFMNCA5bDMtNnoiIGZpbGw9IiNmZmZmZmYiLz48L3N2Zz4=);
        }}

        /* ===== 进度条 ===== */
        QProgressBar {{
            background: {t.surface_hover};
            border: none;
            border-radius: 6px;
            height: 8px;
            text-align: center;
            color: {t.fg_muted};
        }}
        QProgressBar::chunk {{
            background: {t.accent};
            border-radius: 6px;
        }}

        /* ===== 状态栏 / 工具栏 ===== */
        QStatusBar {{
            background: {t.surface};
            border-top: 1px solid {t.border};
            color: {t.fg_muted};
            padding: 4px 10px;
        }}
        QToolBar {{
            background: {t.surface};
            border-bottom: 1px solid {t.border};
            spacing: 8px;
            padding: 6px 10px;
        }}
        QToolBar QToolButton {{
            background: transparent;
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 6px 12px;
        }}
        QToolBar QToolButton:hover {{ background: {t.surface_hover}; }}

        /* ===== 滚动条 ===== */
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {t.border};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {t.fg_muted}; }}
        QScrollBar:horizontal {{
            background: transparent;
            height: 10px;
        }}
        QScrollBar::handle:horizontal {{
            background: {t.border};
            border-radius: 5px;
            min-width: 30px;
        }}

        /* ===== 提示与菜单 ===== */
        QToolTip {{
            background: {t.fg};
            color: {t.bg};
            border: none;
            border-radius: 6px;
            padding: 6px 10px;
        }}
        QMenu {{
            background: {t.surface};
            border: 1px solid {t.border};
            border-radius: 8px;
            padding: 4px;
        }}
        QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
        QMenu::item:selected {{ background: {t.accent_soft}; color: {t.accent}; }}
        """
