"""依赖注入容器（app/container.py）。

管理服务单例：core 服务以单例注册，GUI 经构造注入。纯 Python。
参考开发文档 §7。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Type, TypeVar

T = TypeVar("T")


class Container:
    def __init__(self) -> None:
        self._singletons: Dict[str, Any] = {}
        self._factories: Dict[str, Callable[[], Any]] = {}

    def register_singleton(self, key: str, factory: Callable[[], Any]) -> None:
        self._factories[key] = factory

    def register_instance(self, key: str, instance: Any) -> None:
        self._singletons[key] = instance

    def get(self, key: str) -> Any:
        if key in self._singletons:
            return self._singletons[key]
        if key in self._factories:
            inst = self._factories[key]()
            self._singletons[key] = inst
            return inst
        raise KeyError(f"未注册的服务：{key}")

    def has(self, key: str) -> bool:
        return key in self._singletons or key in self._factories

    def reset(self) -> None:
        self._singletons.clear()


# 全局容器
container = Container()
