"""可复用 UI 组件（gui/widgets.py）。

提供统一视觉语言的原子组件：Card、SectionTitle、PrimaryButton/GhostButton/
DangerButton、StatCard、ScrollBox。所有组件仅依赖 Qt + theme 的 role 约定，
不依赖具体业务，便于各模块复用。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """圆角卡片容器。传入 accent=True 使用强调色淡背景版本。"""

    def __init__(self, accent: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setProperty("role", "card-accent" if accent else "card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)

    @property
    def body(self) -> QVBoxLayout:
        return self._layout


class SectionTitle(QLabel):
    """小节标题（带强调色左竖条）。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "section")
        self.setIndent(8)


class PrimaryButton(QPushButton):
    """主操作按钮（强调色实心）。

    用于模块内最关键的单次动作（如「开始」「运行」）。
    视觉由 app/theme.py 中 role="primary" 的 QSS 控制。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)


class GhostButton(QPushButton):
    """幽灵按钮（透明描边，次一级操作）。

    role="ghost" 的 QSS 提供轻量描边样式，常用于「取消」「重置」等次级动作。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "ghost")


class DangerButton(QPushButton):
    """危险操作按钮（红色，破坏性动作）。

    role="danger" 的 QSS 提供红色强调样式，仅用于删除/停止等危险操作。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setProperty("role", "danger")


class StatCard(QFrame):
    """指标卡：图标圆 + 标签 + 大数值（+可选辅助说明）。"""

    def __init__(self, icon: str, label: str, value: str = "—",
                 hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setProperty("role", "card")
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        icon_box = QFrame()
        icon_box.setFixedSize(46, 46)
        icon_box.setStyleSheet(
            "background: rgba(59,110,246,0.12); border-radius: 12px;"
        )
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        self._icon = QLabel(icon)
        self._icon.setAlignment(Qt.AlignCenter)
        self._icon.setStyleSheet("font-size: 22px; background: transparent;")
        il.addWidget(self._icon)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self._label = QLabel(label)
        self._label.setProperty("role", "muted")
        self._value = QLabel(value)
        self._value.setProperty("role", "metric")
        self._hint = QLabel(hint)
        self._hint.setProperty("role", "muted")
        self._hint.setStyleSheet("font-size: 11px;")
        text_col.addWidget(self._label)
        text_col.addWidget(self._value)
        if hint:
            text_col.addWidget(self._hint)

        root.addWidget(icon_box)
        root.addLayout(text_col, 1)

    def set_value(self, value: str) -> None:
        """更新指标数值显示（大号粗体文本）。"""
        self._value.setText(value)


class ScrollBox(QScrollArea):
    """可滚动内容容器：内部 widget 带统一内边距，内容过长时滚动。"""

    def __init__(self, widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        lay = QVBoxLayout(container)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(16)
        lay.addWidget(widget, 1)
        self.setWidget(container)
