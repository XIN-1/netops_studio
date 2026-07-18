"""主题与样式（app/theme.py）。

light/dark 设计 token + QSS 渲染。跟随系统或手动切换。
参考文档 §7。纯 Python（仅拼装 QSS 字符串，不实例化 Qt 对象）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ThemeToken:
    name: str
    bg: str
    bg_alt: str
    fg: str
    fg_muted: str
    accent: str
    border: str
    success: str
    danger: str
    warning: str


LIGHT = ThemeToken(
    name="light", bg="#ffffff", bg_alt="#f5f6f8", fg="#1f2329", fg_muted="#8a8f99",
    accent="#2f6fed", border="#e3e6eb", success="#1aab5b", danger="#e54545", warning="#f5a623",
)

DARK = ThemeToken(
    name="dark", bg="#1e1f22", bg_alt="#26282c", fg="#e6e8eb", fg_muted="#9aa0a6",
    accent="#4f8cff", border="#3a3d42", success="#27c06a", danger="#ff6b6b", warning="#ffb340",
)


class Theme:
    def __init__(self, mode: str = "light") -> None:
        self.token = LIGHT if mode == "light" else DARK

    def set_mode(self, mode: str) -> None:
        self.token = LIGHT if mode == "light" else DARK

    def qss(self) -> str:
        t = self.token
        return f"""
        QWidget {{
            background-color: {t.bg};
            color: {t.fg};
            font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            font-size: 13px;
        }}
        QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {{
            background-color: {t.bg_alt};
            border: 1px solid {t.border};
            border-radius: 6px;
            padding: 4px 6px;
        }}
        QPushButton {{
            background-color: {t.accent};
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 6px 14px;
        }}
        QPushButton:hover {{ background-color: {t.accent}; opacity: 0.9; }}
        QPushButton:disabled {{ background-color: {t.border}; color: {t.fg_muted}; }}
        QTableView, QTreeView, QListWidget {{
            background-color: {t.bg_alt};
            border: 1px solid {t.border};
            gridline-color: {t.border};
        }}
        QHeaderView::section {{
            background-color: {t.bg_alt};
            border: 1px solid {t.border};
            padding: 4px;
        }}
        QTabWidget::pane {{ border: 1px solid {t.border}; }}
        QLabel[role="muted"] {{ color: {t.fg_muted}; }}
        QLabel[role="title"] {{ font-size: 16px; font-weight: bold; color: {t.fg}; }}
        """
