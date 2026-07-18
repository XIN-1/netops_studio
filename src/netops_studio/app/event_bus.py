"""事件总线（app/event_bus.py）。

轻量发布/订阅，解耦模块与仪表盘、告警中心。纯 Python，不依赖 Qt。
参考开发文档 §7。
"""

from __future__ import annotations

from typing import Callable, Dict, List


class EventBus:
    """进程内发布/订阅总线。topic 为字符串，支持点分层级（如 'discovery.progress'）。"""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable]] = {}

    def subscribe(self, topic: str, callback: Callable) -> None:
        self._subs.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        if topic in self._subs:
            self._subs[topic] = [c for c in self._subs[topic] if c is not callback]

    def publish(self, topic: str, payload=None) -> None:
        for cb in list(self._subs.get(topic, [])):
            try:
                cb(payload)
            except Exception as exc:  # noqa: BLE001
                # 订阅者异常不应中断发布者
                print(f"[EventBus] 订阅者处理 {topic} 出错: {exc}")

    def clear(self) -> None:
        self._subs.clear()


# 全局单例（应用启动时初始化，供各模块直接引用）
bus = EventBus()
