"""网络发现模块（gui/discovery_module.py）。对应 core/discovery.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker, bus
from ..app.async_worker import JobBase
from ..core import discovery
from .widgets import Card, GhostButton, PrimaryButton, SectionTitle


class DiscoveryJob(JobBase):
    """发现扫描任务。

    在 AsyncWorker 的后台线程中执行 ``core.discovery.scan_network``，
    通过 ``on_progress`` 回调把进度转发到 ``signals.progress``，
    完成后把主机列表通过 ``signals.result`` 上报。JobBase 提供协作式取消：
    当 ``worker.cancel()`` 被调用时，scan_network 内部应周期性检查取消标志
    以尽快退出（避免硬杀线程）。
    """

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
    """网段扫描与资产发现模块（对应 core/discovery.py）。

    用户在输入区填入 CIDR 后点击「扫描」，任务经 AsyncWorker 提交到后台线程，
    进度条实时更新；结果以表格展示，并逐条 publish ``discovery.host`` 事件
    供仪表盘聚合。
    """

    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel("资产与发现")
        t.setProperty("role", "title")
        s = QLabel("网段扫描 · 主机 / MAC / 厂商识别")
        s.setProperty("role", "subtitle")
        head.addWidget(t)
        head.addWidget(s)
        root.addLayout(head)

        card = Card()
        card.body.addWidget(SectionTitle("扫描范围"))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.cidr = QLineEdit("192.168.1.0/24")
        form.addRow("目标网段", self.cidr)
        card.body.addLayout(form)

        btn_row = QHBoxLayout()
        self.run_btn = PrimaryButton("扫描")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = GhostButton("停止")
        # 协作式取消：将「停止」按钮连接到 worker.cancel，由 JobBase 在后台轮询取消标志
        self.stop_btn.clicked.connect(self.worker.cancel)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        card.body.addLayout(btn_row)
        self.bar = QProgressBar()
        card.body.addWidget(self.bar)
        root.addWidget(card)

        table_card = Card()
        table_card.body.addWidget(SectionTitle("发现结果"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["IP", "主机名", "MAC", "厂商"])
        self.table.horizontalHeader().setStretchLastSection(True)
        table_card.body.addWidget(self.table, 1)
        root.addWidget(table_card, 1)

    def _run(self) -> None:
        """清空旧结果并提交扫描任务到后台线程。"""
        self.table.setRowCount(0)
        job = DiscoveryJob(self.cidr.text())
        self.worker.submit(job, on_result=self._show, on_progress=self._prog)

    def _prog(self, done: int, total: int) -> None:
        """进度回调：根据已扫/总数设置进度条。"""
        self.bar.setMaximum(total)
        self.bar.setValue(done)

    def _show(self, hosts) -> None:
        """结果回调：填满表格并逐条 publish ``discovery.host`` 事件。"""
        self.bar.setValue(self.bar.maximum())
        self.table.setRowCount(len(hosts))
        for i, h in enumerate(hosts):
            self.table.setItem(i, 0, QTableWidgetItem(h.ip))
            self.table.setItem(i, 1, QTableWidgetItem(h.hostname))
            self.table.setItem(i, 2, QTableWidgetItem(h.mac))
            self.table.setItem(i, 3, QTableWidgetItem(h.vendor))
            bus.publish("discovery.host", h)
