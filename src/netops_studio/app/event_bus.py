"""事件总线（app/event_bus.py）。

轻量发布/订阅，解耦模块与仪表盘、告警中心。纯 Python，不依赖 Qt。
对应开发文档 §7。

设计要点：
- topic 为字符串，约定使用点分层级命名（如 'discovery.progress'、'alert.new'），
  便于按前缀做语义分组（当前为精确匹配，不做通配订阅）。
- publish 采用「尽力投递」：单个订阅者抛错只打印日志，不中断其余订阅者。
- 线程安全说明见下方各方法注释（当前实现未加锁，跨线程订阅/退订需上层保证顺序）。
"""

from __future__ import annotations

from typing import Callable, Dict, List


class EventBus:
    """进程内发布/订阅总线。topic 为字符串，支持点分层级（如 'discovery.progress'）。"""

    def __init__(self) -> None:
        # topic -> [订阅回调]。回调以「对象同一性」存储（见 unsubscribe 说明）。
        self._subs: Dict[str, List[Callable]] = {}

    def subscribe(self, topic: str, callback: Callable) -> None:
        # setdefault 保证 topic 首次订阅时初始化空列表，再追加回调。
        self._subs.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        # 注意：此处以 `c is not callback` 做身份比较，因此传入的 callback 必须
        # 与订阅时**同一个对象**。对模块级函数 / lambda 没问题；但对「绑定方法」
        # （如 self.on_event）而言，每次属性访问都会生成新对象，若用绑定方法订阅
        # 后将无法被此处匹配移除（建议订阅/退订统一用同一函数引用或 functools.partial）。
        if topic in self._subs:
            self._subs[topic] = [c for c in self._subs[topic] if c is not callback]

    def publish(self, topic: str, payload=None) -> None:
        # 先 list(...) 拷贝一份回调列表再遍历，避免遍历过程中（因订阅者内部又
        # 触发 subscribe/unsubscribe）修改原列表导致迭代异常；同时隔离了对 _subs
        # 字典本身的读操作，配合 CPython GIL 的单字节码原子性，单 topic 投递是安全的。
        for cb in list(self._subs.get(topic, [])):
            try:
                cb(payload)
            except Exception as exc:  # noqa: BLE001
                # 订阅者异常不应中断发布者（否则一个坏订阅者会拖累所有其它订阅者）
                print(f"[EventBus] 订阅者处理 {topic} 出错: {exc}")

    def clear(self) -> None:
        # 清空全部订阅关系（如应用退出或测试隔离时使用）。
        self._subs.clear()


# 全局单例（应用启动时初始化，供各模块直接引用）
bus = EventBus()
