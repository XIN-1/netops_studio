"""连通性诊断模块（gui/diagnostic_module.py）。对应 core/diagnostics.py。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import diagnostics
from .widgets import Card, GhostButton, PrimaryButton, SectionTitle


class DiagnosticJob(JobBase):
    """在后台线程执行诊断（协作式取消）。"""

    def __init__(self, op: str, target: str, ports: str = "") -> None:
        super().__init__()
        self.op = op
        self.target = target
        self.ports = ports

    def run_job(self) -> None:
        if self.op == "Ping":
            res = diagnostics.ping(self.target, count=4)
            self.signals.result.emit(res)
        elif self.op == "Traceroute":
            res = diagnostics.traceroute(self.target)
            self.signals.result.emit(res)
        elif self.op == "端口扫描":
            res = diagnostics.port_scan(self.target, self.ports or "1-1024")
            self.signals.result.emit(res)
        elif self.op == "DNS 查询":
            res = diagnostics.dns_query(self.target, "A")
            self.signals.result.emit(res)
        elif self.op == "HTTP 探测":
            res = diagnostics.http_probe(self.target)
            self.signals.result.emit(res)


class DiagnosticModule(QWidget):
    """连通性诊断模块（对应 core/diagnostics.py）。

    支持 Ping/Traceroute/端口扫描/DNS 查询/HTTP 探测五类操作，任务经 AsyncWorker
    后台执行，进度标签实时更新。结果根据类型自适应渲染：标量指标对象显示为
    「字段/值」双列表，端口扫描结果则渲染为「端口/状态/服务/错误」四列表。
    """

    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel("连通性诊断")
        t.setProperty("role", "title")
        s = QLabel("Ping / Traceroute / 端口扫描 / DNS / HTTP 探测")
        s.setProperty("role", "subtitle")
        head.addWidget(t)
        head.addWidget(s)
        root.addLayout(head)

        card = Card()
        card.body.addWidget(SectionTitle("诊断参数"))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.op = QComboBox()
        self.op.addItems(["Ping", "Traceroute", "端口扫描", "DNS 查询", "HTTP 探测"])
        self.target = QLineEdit("8.8.8.8")
        self.ports = QLineEdit("22,80,443,3389")
        form.addRow("操作", self.op)
        form.addRow("目标", self.target)
        form.addRow("端口(扫描用)", self.ports)
        card.body.addLayout(form)

        btn_row = QHBoxLayout()
        self.run_btn = PrimaryButton("运行")
        self.run_btn.clicked.connect(self._run)
        self.stop_btn = GhostButton("停止")
        self.stop_btn.clicked.connect(self.worker.cancel)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        card.body.addLayout(btn_row)
        root.addWidget(card)

        self.progress = QLabel("就绪")
        self.progress.setProperty("role", "muted")
        root.addWidget(self.progress)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段", "值", "", ""])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.raw = QTextEdit()
        self.raw.setReadOnly(True)
        root.addWidget(self.raw)

    def _run(self) -> None:
        """清空上一次结果并提交诊断任务到后台线程。"""
        self.table.setRowCount(0)
        self.raw.clear()
        job = DiagnosticJob(self.op.currentText(), self.target.text(), self.ports.text())
        self.worker.submit(job, on_result=self._show, on_progress=self._prog)

    def _prog(self, done: int, total: int) -> None:
        """进度回调：更新「就绪/进度/完成」状态标签。"""
        self.progress.setText(f"进度 {done}/{total}")

    def _show(self, res) -> None:
        """结果回调：标量对象渲染为字段表，端口扫描列表渲染为四列表。"""
        self.progress.setText("完成")
        self.raw.setPlainText(getattr(res, "raw", str(res)))
        rows = []
        for k in ("target", "transmitted", "received", "loss_percent",
                 "min_ms", "avg_ms", "max_ms", "success"):
            if hasattr(res, k):
                rows.append((k, str(getattr(res, k))))
        if isinstance(res, list):  # 端口扫描结果
            self.table.setColumnCount(4)
            self.table.setHorizontalHeaderLabels(["端口", "状态", "服务", "错误"])
            self.table.setRowCount(len(res))
            for i, r in enumerate(res):
                self.table.setItem(i, 0, QTableWidgetItem(str(r.port)))
                self.table.setItem(i, 1, QTableWidgetItem(r.state))
                self.table.setItem(i, 2, QTableWidgetItem(r.service))
                self.table.setItem(i, 3, QTableWidgetItem(r.error))
            return
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["字段", "值"])
        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(k))
            self.table.setItem(i, 1, QTableWidgetItem(v))
