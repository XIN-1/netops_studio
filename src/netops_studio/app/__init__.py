"""应用服务层。

包含：应用外壳、TabRegistry（插件式注册/懒加载）、EventBus（发布订阅）、
AsyncWorker（协作式异步）、Container（DI）、Theme（主题）、i18n（多语言）。
"""

from .event_bus import EventBus, bus
from .container import Container, container
from .tab_registry import TabDescriptor, TabRegistry
from .async_worker import AsyncWorker, JobBase
from .theme import Theme, ThemeToken
from .i18n import I18n, tr, set_locale

__all__ = [
    "EventBus", "bus", "Container", "container", "TabDescriptor", "TabRegistry",
    "AsyncWorker", "JobBase", "Theme", "ThemeToken", "I18n", "tr", "set_locale",
]
