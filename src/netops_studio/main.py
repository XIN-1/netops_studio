"""NetOps Studio 入口（main.py）。

程序启动流程：解析路径 -> 加载配置 -> 初始化主题/语言 -> 注入服务单例到容器 ->
构建 Tab 注册表 -> 创建并显示主窗口 -> 进入 Qt 事件循环。对应开发文档 §4 / §10。
"""

from __future__ import annotations

import os
import sys

import yaml

from .app import Theme, TabRegistry, TabDescriptor, container, set_locale
from .app.application import NetOpsApplication
from .app.event_bus import bus

# PKG_ROOT 即本文件所在目录（src/netops_studio）；DATA_DIR 为「包内 data/」子目录，
# 用于存放 config.yaml 等运行时可写数据（并非与 src 平级的 data/）。
PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PKG_ROOT, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.yaml")

# 配置默认值：缺失配置文件时写入；读到的配置缺字段时也以此兜底。
DEFAULT_CONFIG = {
    "theme": "light",
    "language": "zh_CN",
    "default_cidr": "192.168.1.0/24",
    "iperf3_path": "",
}


def load_config() -> dict:
    # 确保 data 目录存在（首次运行或目录被删时自动创建）。
    os.makedirs(DATA_DIR, exist_ok=True)
    # 无配置文件则写入默认并直接返回。
    if not os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(DEFAULT_CONFIG, f, allow_unicode=True)
        return dict(DEFAULT_CONFIG)
    # 已有配置：解析；为空/解析失败则用默认兜底（避免 None 导致后续 .get 报错）。
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or dict(DEFAULT_CONFIG)


def build_registry() -> TabRegistry:
    """注册全部 20 个功能 Tab（按阶段 1→2→3 顺序），返回 TabRegistry。

    注册顺序即阶段分组顺序；同一阶段内的展示顺序由 NavPanel 再按 (stage, title)
    排序决定。各 factory 为 lambda 延迟构造（真正的 widget 在首次切换时才创建）。
    """
    reg = TabRegistry()
    # ---- 阶段 1：基础运维（MVP）----
    from .gui.dashboard import Dashboard
    from .gui.discovery_module import DiscoveryModule
    from .gui.diagnostic_module import DiagnosticModule
    from .gui.speed_test_module import SpeedTestModule
    from .gui.subnet_module import SubnetModule
    from .gui.codec_module import CodecModule
    from .gui.toolbox_module import ToolboxModule

    # ---- 阶段 2：监控排障 ----
    from .gui.config_module import ConfigModule
    from .gui.monitor_module import MonitorModule
    from .gui.security_module import SecurityModule
    from .gui.troubleshoot_module import TroubleshootModule
    from .gui.capture_module import CaptureModule
    from .gui.aviot_module import AvIotModule
    from .gui.report_module import ReportModule
    from .gui.ipam_module import IpamModule
    from .gui.flow_module import FlowModule
    from .gui.oob_module import OobModule

    # ---- 阶段 3：平台智能 ----
    from .gui.ai_module import AiModule
    from .gui.integration_module import IntegrationModule
    from .gui.platform_module import PlatformModule

    reg.register(TabDescriptor("dashboard", "仪表盘", "📊", stage=1, factory=lambda: Dashboard()))
    reg.register(TabDescriptor("discovery", "资产与发现", "🔍", stage=1, factory=lambda: DiscoveryModule()))
    reg.register(TabDescriptor("diagnostics", "连通性诊断", "🩺", stage=1, factory=lambda: DiagnosticModule()))
    reg.register(TabDescriptor("speedtest", "性能与测速", "🚀", stage=1, factory=lambda: SpeedTestModule()))
    reg.register(TabDescriptor("subnet", "子网计算器", "🧮", stage=1, factory=lambda: SubnetModule()))
    reg.register(TabDescriptor("codec", "编解码工具", "🔑", stage=1, factory=lambda: CodecModule()))
    reg.register(TabDescriptor("toolbox", "工具箱", "🧰", stage=1, factory=lambda: ToolboxModule()))

    reg.register(TabDescriptor("config", "配置管理", "⚙️", stage=2, factory=lambda: ConfigModule()))
    reg.register(TabDescriptor("monitor", "监控与告警", "📡", stage=2, factory=lambda: MonitorModule()))
    reg.register(TabDescriptor("security", "安全管理", "🛡️", stage=2, factory=lambda: SecurityModule()))
    reg.register(TabDescriptor("troubleshoot", "专项排障", "🧯", stage=2, factory=lambda: TroubleshootModule()))
    reg.register(TabDescriptor("capture", "抓包分析", "📦", stage=2, factory=lambda: CaptureModule()))
    reg.register(TabDescriptor("aviot", "音视频物联", "🎥", stage=2, factory=lambda: AvIotModule()))
    reg.register(TabDescriptor("report", "报表自动化", "📑", stage=2, factory=lambda: ReportModule()))
    reg.register(TabDescriptor("ipam", "IP 地址管理", "🗺️", stage=2, factory=lambda: IpamModule()))
    reg.register(TabDescriptor("flow", "流量深度分析", "🌊", stage=2, factory=lambda: FlowModule()))
    reg.register(TabDescriptor("oob", "带外与机房", "🖥️", stage=2, factory=lambda: OobModule()))

    reg.register(TabDescriptor("ai", "AI 智能助手", "🤖", stage=3, factory=lambda: AiModule()))
    reg.register(TabDescriptor("integration", "集成与 API", "🔌", stage=3, factory=lambda: IntegrationModule()))
    reg.register(TabDescriptor("platform", "平台与权限", "🔐", stage=3, factory=lambda: PlatformModule()))
    return reg


def main() -> int:
    app = NetOpsApplication(sys.argv)
    cfg = load_config()

    # 主题与语言依据配置初始化（缺省 light / zh_CN）。
    theme = Theme(cfg.get("theme", "light"))
    set_locale(cfg.get("language", "zh_CN"))

    # 注入服务单例到容器，供各模块按需解析（key: theme / config / bus）。
    container.register_instance("theme", theme)
    container.register_instance("config", cfg)
    container.register_instance("bus", bus)

    registry = build_registry()

    from .gui.shell.main_window import MainWindow

    win = MainWindow(registry, theme)
    win.show()

    # 默认进入仪表盘（factory 存在时才切换，避免空注册表时出错）。
    first = registry.get("dashboard")
    if first and first.factory:
        win._select("dashboard")

    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
