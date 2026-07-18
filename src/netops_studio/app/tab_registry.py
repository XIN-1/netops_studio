"""插件式 Tab 注册与懒加载（app/tab_registry.py）。

register(TabDescriptor{id,title,icon,factory,stage})；按 tab_id 懒加载构建/切换，
避免冷启动卡顿。参考文档 §7。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from PySide6.QtWidgets import QWidget


@dataclass
class TabDescriptor:
    id: str
    title: str
    icon: str = ""
    stage: int = 1                       # 阶段；未到达阶段显示为占位/禁用
    enabled: bool = True
    factory: Optional[Callable[[], QWidget]] = None
    _instance: Optional[QWidget] = field(default=None, repr=False)

    def build(self) -> Optional[QWidget]:
        if self._instance is None and self.factory is not None:
            self._instance = self.factory()
        return self._instance


class TabRegistry:
    def __init__(self) -> None:
        self._tabs: Dict[str, TabDescriptor] = {}
        self._order: List[str] = []

    def register(self, desc: TabDescriptor) -> None:
        if desc.id in self._tabs:
            raise ValueError(f"Tab 已存在：{desc.id}")
        self._tabs[desc.id] = desc
        self._order.append(desc.id)

    def get(self, tab_id: str) -> Optional[TabDescriptor]:
        return self._tabs.get(tab_id)

    def descriptor(self, tab_id: str) -> Optional[TabDescriptor]:
        return self._tabs.get(tab_id)

    def all(self) -> List[TabDescriptor]:
        return [self._tabs[i] for i in self._order]

    def enable_stage(self, stage: int) -> None:
        """点亮到达阶段的 Tab。"""
        for d in self._tabs.values():
            if d.stage <= stage:
                d.enabled = True

    def ordered(self) -> List[TabDescriptor]:
        return [self._tabs[i] for i in self._order]
