"""插件式 Tab 注册与懒加载（app/tab_registry.py）。

职责：以声明式 TabDescriptor（id/title/icon/factory/stage/enabled）登记全部功能页，
并在运行时按 tab_id 懒加载构建与切换，避免冷启动一次性构造所有模块导致卡顿。
对应开发文档 §7。

关键机制：
- 懒加载：factory 只在首次 `build()` 时调用，构造结果缓存进 `_instance`，后续
  直接复用（单例缓存），保证同一 Tab 的 widget 在多次切换间保持状态。
- 阶段化：stage 用于「分批开放」。未到达阶段的 Tab 以 enabled=False 占位，由
  导航面板渲染为禁用 / 未开放项；enable_stage() 用于点亮已到达阶段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from PySide6.QtWidgets import QWidget


@dataclass
class TabDescriptor:
    """单个功能页的注册元数据 + 懒加载句柄。

    factory 为无参构造器，返回该 Tab 的根 QWidget；build() 负责「首次构造并缓存」。
    """

    id: str
    title: str
    icon: str = ""
    stage: int = 1                       # 阶段；未到达阶段显示为占位/禁用
    enabled: bool = True
    factory: Optional[Callable[[], QWidget]] = None
    # 懒加载缓存：首次 build() 后保存 widget 实例，实现「单例缓存、重复切换复用」。
    _instance: Optional[QWidget] = field(default=None, repr=False)

    def build(self) -> Optional[QWidget]:
        # 懒加载：仅当尚未构造（_instance 为 None）且提供了 factory 时才真正构建，
        # 并将结果缓存进 _instance；之后调用直接返回缓存，保证单例语义。
        # 若 factory 返回 None，则 _instance 仍为 None，下次 build 会再次尝试（不缓存空结果）。
        if self._instance is None and self.factory is not None:
            self._instance = self.factory()
        return self._instance


class TabRegistry:
    """Tab 注册表：维护 id -> TabDescriptor 映射与注册顺序。"""

    def __init__(self) -> None:
        self._tabs: Dict[str, TabDescriptor] = {}
        self._order: List[str] = []  # 注册顺序（稳定的遍历/展示顺序）

    def register(self, desc: TabDescriptor) -> None:
        # 重复 id 视为编程错误，直接抛异常，避免后面静默覆盖导致行为不可预期。
        if desc.id in self._tabs:
            raise ValueError(f"Tab 已存在：{desc.id}")
        self._tabs[desc.id] = desc
        self._order.append(desc.id)

    def get(self, tab_id: str) -> Optional[TabDescriptor]:
        return self._tabs.get(tab_id)

    def descriptor(self, tab_id: str) -> Optional[TabDescriptor]:
        # 与 get() 行为完全一致（历史别名）；二者可保留其一。
        return self._tabs.get(tab_id)

    def all(self) -> List[TabDescriptor]:
        return [self._tabs[i] for i in self._order]

    def enable_stage(self, stage: int) -> None:
        """点亮到达阶段的 Tab（stage <= 给定值者启用）。

        注意：本方法为「单向开放」——只把满足条件的置为 enabled，不会反向禁用；
        若后续需要按更低阶段回收，应显式设置各 descriptor.enabled。
        """
        for d in self._tabs.values():
            if d.stage <= stage:
                d.enabled = True

    def ordered(self) -> List[TabDescriptor]:
        # 与 all() 行为完全一致（历史别名）；二者可保留其一。
        return [self._tabs[i] for i in self._order]
