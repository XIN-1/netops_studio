"""左侧导航面板（gui/shell/nav_panel.py）。

品牌头部 + 按阶段分组的可选列表（自定义 #NavList 样式，见 theme.py）。
禁用项用作分组小标题（复用了 NavList::item:disabled 样式），选中项由
theme 的 NavList::item:selected 渲染。

构造时即根据 TabRegistry 全量构建列表项（列表本身很轻；真正的模块 widget
仍由 TabRegistry 懒加载，不在本面板构造）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from ...app.tab_registry import TabRegistry

# 各阶段在导航中显示的分组标题；缺省阶段回退为「阶段 N」。
_STAGE_TITLE = {1: "阶段一 · 基础运维", 2: "阶段二 · 监控排障", 3: "阶段三 · 平台智能"}

# 列表项存放 tab_id 所用的 Qt ItemData role（使用 100 作为 UserRole 区间内的自定义键）。
_ITEM_ROLE_TAB_ID = 100


class NavPanel(QWidget):
    """侧边导航：品牌头 + 阶段分组的可选 Tab 列表。点击项时回调 on_select(tab_id)。"""

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
        self.list.setObjectName("NavList")  # 锚定 theme 的 QListWidget#NavList 样式
        self.registry = registry
        self.on_select = on_select

        # 按 (stage, title) 排序，保证同阶段内顺序稳定且跨阶段分组连续。
        # 注意：排序键为 title 字符串，中文按 Unicode 码位排序，与 main.py 注册顺序不一定一致。
        ordered = sorted(registry.ordered(), key=lambda d: (d.stage, d.title))
        last_stage = None
        for desc in ordered:
            # 阶段切换时插入一个不可选的分组标题项（以 disabled 态复用样式作标题）。
            if desc.stage != last_stage:
                head = QListWidgetItem(_STAGE_TITLE.get(desc.stage, f"阶段 {desc.stage}"))
                head.setFlags(head.flags() & ~Qt.ItemIsEnabled)
                head.setTextAlignment(Qt.AlignLeft)
                self.list.addItem(head)
                last_stage = desc.stage
            item = QListWidgetItem(f"  {desc.icon}   {desc.title}")
            # 用自定义 role 把 tab_id 绑到列表项，点击时取回以定位 TabDescriptor。
            item.setData(_ITEM_ROLE_TAB_ID, desc.id)
            if not desc.enabled:
                # 未开放 Tab：禁用并追加「（未开放）」提示（样式由 disabled 态呈现）。
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                item.setText(f"  {desc.icon}   {desc.title}（未开放）")
            self.list.addItem(item)

        self.list.currentItemChanged.connect(self._changed)

        root.addWidget(brand)
        root.addWidget(self.list, 1)

    def _changed(self, current, _prev) -> None:
        # 仅当切到「可选」项（带 tab_id）时才回调；分组标题/未开放项 data 为 None 会被忽略。
        if current is None:
            return
        tab_id = current.data(_ITEM_ROLE_TAB_ID)
        if tab_id is None:
            return
        self.on_select(tab_id)
