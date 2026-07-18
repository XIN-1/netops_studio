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

    @staticmethod
    def _key(cb: Callable):
        """归一化回调身份，使「同一对象的同一绑定方法」可被稳定匹配。

        - 普通函数 / lambda：以对象自身为 key（``c is callback`` 的等价形式）。
        - 绑定方法（``self.method``）：每次访问都会生成新对象，故改用
          ``(func, self)`` 作为身份——同一实例的同一方法视为同一订阅者，
          从而支持正确退订（此前用身份比较导致绑定方法无法被移除）。
        """
        if hasattr(cb, "__self__") and hasattr(cb, "__func__"):
            return ("method", cb.__func__, cb.__self__)
        return ("other", cb)

    def unsubscribe(self, topic: str, callback: Callable) -> None:
        # 以归一化 key 比较，使绑定方法也能被精确匹配移除（修复订阅泄漏）。
        if topic in self._subs:
            key = self._key(callback)
            self._subs[topic] = [c for c in self._subs[topic] if self._key(c) != key]

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
