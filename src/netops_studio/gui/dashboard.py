"""仪表盘（gui/dashboard.py）。

订阅 EventBus 中 发现/测速/监控 事件，聚合渲染指标卡、近期设备、系统健康。
参考文档 §6.5。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QLabel, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget,
)

from ..app import bus
from ..app.i18n import tr
from .widgets import Card, ScrollBox, SectionTitle, StatCard


class Dashboard(QWidget):
    """网络态势总览面板。

    本地聚合来自事件总线（bus）的事件：
      - ``discovery.host``：新发现主机，累加在线数并刷新平均延迟
      - ``speedtest.result``：测速结果，更新吞吐量
      - ``alert``：告警事件，累加告警计数
    并渲染指标卡与近期设备列表。所有数据均为本面板内部状态，
    由各订阅回调在事件到达时增量更新后统一调用 ``_refresh`` 重绘。
    """

    def __init__(self) -> None:
        super().__init__()
        self.online_count = 0
        self.avg_latency: float | None = None
        self.last_throughput = 0.0
        self.alerts = 0
        self.devices: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        # 标题区
        head = QVBoxLayout()
        head.setSpacing(2)
        title = QLabel(tr("nav.dashboard"))
        title.setProperty("role", "title")
        sub = QLabel("网络运行态势总览 · 实时聚合各模块事件")
        sub.setProperty("role", "subtitle")
        head.addWidget(title)
        head.addWidget(sub)
        root.addLayout(head)

        # 指标卡行
        self.cards = {
            "online": StatCard("🟢", tr("common.online"), "— 台", "在线设备"),
            "latency": StatCard("⚡", "平均延迟", "— ms", "近期探测均值"),
            "throughput": StatCard("📶", "吞吐量", "0 Mbps", "最近一次测速"),
            "alerts": StatCard("🔔", "告警", "0", "累计触发"),
        }
        row = QHBoxLayout()
        row.setSpacing(16)
        for c in self.cards.values():
            row.addWidget(c, 1)
        root.addLayout(row)

        # 近期设备卡
        dev_card = Card()
        dev_card.body.addWidget(SectionTitle("近期发现设备"))
        self.device_list = QListWidget()
        self.device_list.setMinimumHeight(180)
        dev_card.body.addWidget(self.device_list, 1)
        root.addWidget(dev_card, 1)

        # 订阅事件总线：事件由 discovery/speed_test/告警模块 publish，本面板被动聚合
        bus.subscribe("discovery.host", self._on_host)
        bus.subscribe("speedtest.result", self._on_speed)
        bus.subscribe("alert", self._on_alert)

    def _on_host(self, host) -> None:
        """处理 ``discovery.host`` 事件：累加在线设备并刷新平均延迟。"""
        self.online_count += 1
        if host is not None and getattr(host, "latency_ms", None):
            self.avg_latency = round(
                ((self.avg_latency or 0) * (self.online_count - 1) + host.latency_ms) / self.online_count, 1
            )
        self.devices.append(host)
        item = QListWidgetItem(f"{getattr(host, 'ip', '?')}   {getattr(host, 'hostname', '')}")
        self.device_list.addItem(item)
        self._refresh()

    def _on_speed(self, result) -> None:
        """处理 ``speedtest.result`` 事件：提取成功测速的带宽作为吞吐量。"""
        if result is not None and getattr(result, "success", False):
            self.last_throughput = getattr(result, "bandwidth_mbps", 0.0)
        self._refresh()

    def _on_alert(self, payload) -> None:
        """处理 ``alert`` 事件：累加告警计数。"""
        self.alerts += 1
        self._refresh()

    def _refresh(self) -> None:
        """重绘四张指标卡；在所有订阅回调末尾统一调用，避免重复刷新。"""
        self.cards["online"].set_value(f"{self.online_count} 台")
        self.cards["latency"].set_value(f"{self.avg_latency if self.avg_latency else '—'} ms")
        self.cards["throughput"].set_value(f"{self.last_throughput} Mbps")
        self.cards["alerts"].set_value(f"{self.alerts}")
