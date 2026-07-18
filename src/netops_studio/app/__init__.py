"""应用基础设施层（app 包）。

本包承载 NetOps Studio 的「基础设施 / 应用服务」层，向上为 GUI 外壳（gui.shell）
与各业务模块（gui.*）提供可复用的横切能力；向下不依赖任何具体业务实现，仅保持
纯 Python 与 Qt 的最小耦合。各子模块职责如下（均对应开发文档 §7，application 另见 §4）：

- application  : QApplication 单例封装与全局异常兜底。
- event_bus    : 进程内发布/订阅总线，解耦模块与仪表盘、告警中心。
- container    : 轻量依赖注入容器，管理 core 服务单例 / 工厂。
- tab_registry : 插件式 Tab 注册与懒加载，避免冷启动卡顿。
- i18n         : 多语言资源加载与 tr() 取词。
- async_worker : QRunnable + threading.Event 协作式异步工作器。
- theme        : 设计 token + QSS 渲染，提供 light/dark 双主题。

本文件作为包入口，统一再导出上述公共类型与全局单例（bus / container），
供 gui 层以 `from ...app import ...` 的相对导入方式引用。
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
