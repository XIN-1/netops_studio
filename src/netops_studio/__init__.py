"""NetOps Studio / 网维工作台。

面向网络工程师与 IT 运维的集成化桌面运维工作台。
包结构：
    app/   应用服务层（外壳、TabRegistry、EventBus、AsyncWorker、DI、主题、i18n）
    core/  核心引擎层（纯 Python，禁止 import PySide6）
    gui/   表现层（PySide6 各功能模块 Widget）
"""

__version__ = "0.2.0"
__app_name__ = "NetOps Studio"
