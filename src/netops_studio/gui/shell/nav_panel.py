"""左侧导航面板（gui/shell/nav_panel.py）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from ...app import tr
from ...app.tab_registry import TabRegistry


class NavPanel(QWidget):
    def __init__(self, registry: TabRegistry, on_select) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        self.list = QListWidget()
        self.registry = registry
        self.on_select = on_select
        self._items: dict = {}
        for desc in registry.ordered():
            item = QListWidgetItem(desc.icon + "  " + desc.title)
            item.setData(100, desc.id)
            if not desc.enabled:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)  # 占位禁用
                item.setText(f"{desc.icon}  {desc.title}（阶段{desc.stage}）")
            self._items[desc.id] = item
            self.list.addItem(item)
        self.list.currentItemChanged.connect(self._changed)
        root.addWidget(self.list)

    def _changed(self, current, _prev) -> None:
        if current is None:
            return
        tab_id = current.data(100)
        self.on_select(tab_id)
