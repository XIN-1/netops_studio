"""网络发现模块（gui/discovery_module.py）。对应 core/discovery.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QProgressBar,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker, bus
from ..app.async_worker import JobBase
from ..core import discovery


class DiscoveryJob(JobBase):
    def __init__(self, cidr: str) -> None:
        super().__init__()
        self.cidr = cidr

    def run_job(self) -> None:
        hosts = discovery.scan_network(
            self.cidr,
            on_progress=lambda d, t: self.signals.progress.emit(d, t),
        )
        self.signals.result.emit(hosts)


class DiscoveryModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.cidr = QLineEdit("192.168.1.0/24")
        form.addRow("目标网段", self.cidr)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("扫描")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.worker.cancel)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.bar = QProgressBar()
        root.addWidget(self.bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["IP", "主机名", "MAC", "厂商"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

    def _run(self) -> None:
        self.table.setRowCount(0)
        job = DiscoveryJob(self.cidr.text())
        self.worker.submit(job, on_result=self._show, on_progress=self._prog)

    def _prog(self, done: int, total: int) -> None:
        self.bar.setMaximum(total)
        self.bar.setValue(done)

    def _show(self, hosts) -> None:
        self.bar.setValue(self.bar.maximum())
        self.table.setRowCount(len(hosts))
        for i, h in enumerate(hosts):
            self.table.setItem(i, 0, QTableWidgetItem(h.ip))
            self.table.setItem(i, 1, QTableWidgetItem(h.hostname))
            self.table.setItem(i, 2, QTableWidgetItem(h.mac))
            self.table.setItem(i, 3, QTableWidgetItem(h.vendor))
            # 经事件总线通知仪表盘（主线程）
            bus.publish("discovery.host", h)
