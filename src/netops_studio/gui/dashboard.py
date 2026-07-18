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

        # 订阅事件总线
        bus.subscribe("discovery.host", self._on_host)
        bus.subscribe("speedtest.result", self._on_speed)
        bus.subscribe("alert", self._on_alert)

    def _on_host(self, host) -> None:
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
        if result is not None and getattr(result, "success", False):
            self.last_throughput = getattr(result, "bandwidth_mbps", 0.0)
        self._refresh()

    def _on_alert(self, payload) -> None:
        self.alerts += 1
        self._refresh()

    def _refresh(self) -> None:
        self.cards["online"].set_value(f"{self.online_count} 台")
        self.cards["latency"].set_value(f"{self.avg_latency if self.avg_latency else '—'} ms")
        self.cards["throughput"].set_value(f"{self.last_throughput} Mbps")
        self.cards["alerts"].set_value(f"{self.alerts}")
