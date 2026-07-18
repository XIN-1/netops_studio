"""左侧导航面板（gui/shell/nav_panel.py）。

品牌头部 + 按阶段分组的可选列表（自定义 #NavList 样式，见 theme.py）。
禁用项用作分组小标题，选中项由 theme 的 NavList::item:selected 渲染。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from ...app import tr
from ...app.tab_registry import TabRegistry

_STAGE_TITLE = {1: "阶段一 · 基础运维", 2: "阶段二 · 监控排障", 3: "阶段三 · 平台智能"}


class NavPanel(QWidget):
    def __init__(self, registry: TabRegistry, on_select) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 品牌头部
        brand = QWidget()
        brand.setStyleSheet("background: transparent;")
        b_lay = QHBoxLayout(brand)
        b_lay.setContentsMargins(18, 16, 18, 16)
        logo = QLabel("🛰️")
        logo.setStyleSheet("font-size: 26px; background: transparent;")
        b_text = QVBoxLayout()
        b_text.setSpacing(0)
        b_name = QLabel("NetOps Studio")
        b_name.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #3b6ef6; background: transparent;"
        )
        b_sub = QLabel("网维工作台")
        b_sub.setProperty("role", "muted")
        b_sub.setStyleSheet("font-size: 11px; background: transparent;")
        b_text.addWidget(b_name)
        b_text.addWidget(b_sub)
        b_lay.addWidget(logo)
        b_lay.addLayout(b_text, 1)

        # 导航列表
        self.list = QListWidget()
        self.list.setObjectName("NavList")
        self.registry = registry
        self.on_select = on_select

        ordered = sorted(registry.ordered(), key=lambda d: (d.stage, d.title))
        last_stage = None
        for desc in ordered:
            if desc.stage != last_stage:
                head = QListWidgetItem(_STAGE_TITLE.get(desc.stage, f"阶段 {desc.stage}"))
                head.setFlags(head.flags() & ~Qt.ItemIsEnabled)
                head.setTextAlignment(Qt.AlignLeft)
                self.list.addItem(head)
                last_stage = desc.stage
            item = QListWidgetItem(f"  {desc.icon}   {desc.title}")
            item.setData(100, desc.id)
            if not desc.enabled:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setText(f"  {desc.icon}   {desc.title}（未开放）")
            self.list.addItem(item)

        self.list.currentItemChanged.connect(self._changed)

        root.addWidget(brand)
        root.addWidget(self.list, 1)

    def _changed(self, current, _prev) -> None:
        if current is None:
            return
        tab_id = current.data(100)
        if tab_id is None:
            return
        self.on_select(tab_id)
