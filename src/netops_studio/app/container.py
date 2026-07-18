"""依赖注入容器（app/container.py）。

管理服务单例与工厂，解耦「服务创建」与「服务消费」。core 层的服务在此以
单例 / 工厂形式注册，GUI 与各模块通过字符串 key 解析获取，避免层层传参。
纯 Python，不依赖 Qt。对应开发文档 §7。

两种注册语义：
- register_instance：直接放入一个已构造好的对象（立即单例）。
- register_singleton：放入一个**工厂函数**（懒加载），首次 get 时才构造并缓存，
  之后始终返回同一实例。虽名为 singleton，实为「懒加载单例」。

注意：本容器非线程安全，约定在应用启动阶段（单线程）完成注册。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, TypeVar

T = TypeVar("T")  # 预留类型变量（当前解析接口按字符串 key 取 Any，未使用泛型约束）


class Container:
    def __init__(self) -> None:
        # 已构造好的单例实例（register_instance 或直接缓存的工厂产物）。
        self._singletons: Dict[str, Any] = {}
        # 待懒加载的工厂函数（register_singleton 注册）。key 同时存在于两处时，
        # _singletons 优先（见 get）。
        self._factories: Dict[str, Callable[[], Any]] = {}

    def register_singleton(self, key: str, factory: Callable[[], Any]) -> None:
        # 注册工厂：首次 get 时调用 factory() 构造并缓存为单例。
        self._factories[key] = factory

    def register_instance(self, key: str, instance: Any) -> None:
        # 注册一个已存在的实例，立即作为单例生效（覆盖同名工厂的待构造状态）。
        self._singletons[key] = instance

    def get(self, key: str) -> Any:
        # 解析顺序：已缓存单例 -> 懒加载工厂（构造后写回 _singletons 实现单例）-> 报错。
        if key in self._singletons:
            return self._singletons[key]
        if key in self._factories:
            inst = self._factories[key]()
            self._singletons[key] = inst
            return inst
        raise KeyError(f"未注册的服务：{key}")

    def has(self, key: str) -> bool:
        # 只要单例或工厂任一处存在即视为已注册。
        return key in self._singletons or key in self._factories

    def reset(self) -> None:
        # 清空已缓存的单例实例，使工厂可在下次 get 时重新构造。
        # 注意：仅清 _singletons，不清 _factories；工厂定义仍保留，符合「重置运行态」语义。
        self._singletons.clear()


# 全局容器
container = Container()
