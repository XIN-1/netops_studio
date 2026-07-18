"""仪表盘（gui/dashboard.py）。

订阅 EventBus 中 发现/测速/监控 事件，聚合渲染 KPI 卡、近期设备列表。
参考文档 §6.5。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app import bus
from ..app.i18n import tr


class KpiCard(QFrame):
    def __init__(self, title: str, value: str = "—") -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumHeight(80)
        lay = QVBoxLayout(self)
        self._title = QLabel(title)
        self._title.setProperty("role", "muted")
        self._value = QLabel(value)
        self._value.setProperty("role", "title")
        lay.addWidget(self._title)
        lay.addWidget(self._value)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


class Dashboard(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.online_count = 0
        self.avg_latency: float | None = None
        self.last_throughput = 0.0
        self.alerts = 0
        self.devices: list = []

        root = QVBoxLayout(self)
        title = QLabel(tr("nav.dashboard"))
        title.setProperty("role", "title")
        root.addWidget(title)

        # KPI 卡片行
        self.cards = {
            "online": KpiCard(tr("common.online")),
            "latency": KpiCard("平均延迟"),
            "throughput": KpiCard("吞吐 (Mbps)"),
            "alerts": KpiCard("告警"),
        }
        card_row = QHBoxLayout()
        for c in self.cards.values():
            card_row.addWidget(c)
        root.addLayout(card_row)

        # 近期设备
        root.addWidget(QLabel("近期设备"))
        self.device_list = QListWidget()
        root.addWidget(self.device_list)

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
        item = QListWidgetItem(f"{getattr(host, 'ip', '?')}  {getattr(host, 'hostname', '')}")
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
        self.cards["throughput"].set_value(f"{self.last_throughput}")
        self.cards["alerts"].set_value(f"{self.alerts}")
