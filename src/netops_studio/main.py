"""NetOps Studio 入口（main.py）。

初始化容器、加载外壳、注册 tabs。参考文档 §4 / §10。
"""

from __future__ import annotations

import os
import sys

import yaml

from .app import Theme, TabRegistry, TabDescriptor, container, set_locale
from .app.application import NetOpsApplication
from .app.event_bus import bus

# 包目录（src/netops_studio），data 位于同级 data/
PKG_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PKG_ROOT, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "config.yaml")

DEFAULT_CONFIG = {
    "theme": "light",
    "language": "zh_CN",
    "default_cidr": "192.168.1.0/24",
    "iperf3_path": "",
}


def load_config() -> dict:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.isfile(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(DEFAULT_CONFIG, f, allow_unicode=True)
        return dict(DEFAULT_CONFIG)
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or dict(DEFAULT_CONFIG)


def build_registry() -> TabRegistry:
    reg = TabRegistry()
    # ---- MVP（阶段 1）----
    from .gui.dashboard import Dashboard
    from .gui.discovery_module import DiscoveryModule
    from .gui.diagnostic_module import DiagnosticModule
    from .gui.speed_test_module import SpeedTestModule
    from .gui.subnet_module import SubnetModule
    from .gui.codec_module import CodecModule
    from .gui.toolbox_module import ToolboxModule

    # ---- 阶段 2 ----
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

    # ---- 阶段 3 ----
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

    theme = Theme(cfg.get("theme", "light"))
    set_locale(cfg.get("language", "zh_CN"))

    # 注入服务单例
    container.register_instance("theme", theme)
    container.register_instance("config", cfg)
    container.register_instance("bus", bus)

    registry = build_registry()

    from .gui.shell.main_window import MainWindow

    win = MainWindow(registry, theme)
    win.show()

    # 默认进入仪表盘
    first = registry.get("dashboard")
    if first and first.factory:
        win._select("dashboard")

    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
