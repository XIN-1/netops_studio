"""监控与告警模块（gui/monitor_module.py）。对应 core/monitor.py。"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import monitor


_STATUS_COLORS = {
    "ok": QColor("#2e7d32"),
    "warn": QColor("#ef6c00"),
    "crit": QColor("#c62828"),
}


class MonitorJob(JobBase):
    """后台执行 SNMP 轮询；支持单次 / 持续（协作式取消）。"""

    def __init__(self, target: str, oid: str, community: str,
                 version=2, continuous: bool = False, interval: int = 3) -> None:
        super().__init__()
        self.target = target
        self.oid = oid
        self.community = community
        self.version = version
        self.continuous = continuous
        self.interval = interval

    def run_job(self) -> None:
        loop = 0
        while not self.should_stop():
            try:
                results = monitor.snmp_get(self.target, self.oid, self.community, self.version)
            except Exception as exc:  # noqa: BLE001
                self.signals.error.emit(str(exc))
                if not self.continuous:
                    return
                # 持续模式下跳过错过的周期，避免空转报错刷屏
                for _ in range(self.interval * 10):
                    if self.should_stop():
                        return
                    time.sleep(0.1)
                continue
            self.signals.result.emit({
                "loop": loop,
                "results": results,
                "continuous": self.continuous,
            })
            loop += 1
            if not self.continuous:
                return
            for _ in range(self.interval * 10):
                if self.should_stop():
                    return
                time.sleep(0.1)


class MonitorModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        self._syslog: Optional[monitor.SyslogReceiver] = None
        self._rule: Optional[monitor.ThresholdRule] = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ---- SNMP 轮询配置 ----
        form = QFormLayout()
        self.target = QLineEdit("127.0.0.1")
        self.oid = QComboBox()
        for item in monitor.COMMON_OIDS:
            self.oid.addItem(f"{item['name']} ({item['oid']})", item["oid"])
        self.oid.setEditable(True)
        self.community = QLineEdit("public")
        self.version = QComboBox()
        self.version.addItems(["1", "2", "2c"])
        self.version.setCurrentText("2c")
        form.addRow("目标", self.target)
        form.addRow("OID", self.oid)
        form.addRow("社区字串", self.community)
        form.addRow("版本", self.version)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        self.once_btn = QPushButton("单次轮询")
        self.once_btn.clicked.connect(self._poll_once)
        self.cont_btn = QPushButton("持续轮询")
        self.cont_btn.clicked.connect(self._poll_cont)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._stop)
        btn_row.addWidget(self.once_btn)
        btn_row.addWidget(self.cont_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ---- 阈值 ----
        thr = QHBoxLayout()
        self.thr_metric = QLineEdit("指标")
        self.thr_op = QComboBox()
        self.thr_op.addItems([">", "<", ">=", "<=", "=="])
        self.thr_value = QLineEdit("0")
        self.thr_sev = QComboBox()
        self.thr_sev.addItems(["warn", "crit"])
        self.thr_apply = QPushButton("应用阈值")
        self.thr_apply.clicked.connect(self._apply_threshold)
        thr.addWidget(QLabel("阈值:"))
        thr.addWidget(self.thr_metric)
        thr.addWidget(self.thr_op)
        thr.addWidget(self.thr_value)
        thr.addWidget(self.thr_sev)
        thr.addWidget(self.thr_apply)
        root.addLayout(thr)

        self.progress = QLabel("就绪")
        root.addWidget(self.progress)

        # ---- 指标表格 ----
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["指标", "当前值", "状态"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

        # ---- Syslog 接收 ----
        syslog_box = QHBoxLayout()
        self.syslog_toggle = QCheckBox("启用 Syslog 接收")
        self.syslog_toggle.stateChanged.connect(self._toggle_syslog)
        self.syslog_port = QLineEdit("514")
        self.syslog_port.setMaximumWidth(80)
        syslog_box.addWidget(self.syslog_toggle)
        syslog_box.addWidget(QLabel("端口"))
        syslog_box.addWidget(self.syslog_port)
        syslog_box.addStretch()
        root.addLayout(syslog_box)

        self.syslog_list = QListWidget()
        self.syslog_list.setMaximumHeight(160)
        root.addWidget(self.syslog_list)

    # -- SNMP 操作 --
    def _version_int(self):
        return 1 if self.version.currentText() == "1" else 2

    def _poll_once(self) -> None:
        self.worker.cancel()
        self.table.setRowCount(0)
        job = MonitorJob(
            self.target.text(), self.oid.currentData() or self.oid.currentText(),
            self.community.text(), self._version_int(), continuous=False,
        )
        self.worker.submit(job, on_result=self._on_result, on_error=self._on_error)

    def _poll_cont(self) -> None:
        self.worker.cancel()
        self.table.setRowCount(0)
        job = MonitorJob(
            self.target.text(), self.oid.currentData() or self.oid.currentText(),
            self.community.text(), self._version_int(), continuous=True,
        )
        self.worker.submit(job, on_result=self._on_result, on_error=self._on_error)

    def _stop(self) -> None:
        self.worker.cancel()
        self.progress.setText("已停止")

    def _apply_threshold(self) -> None:
        try:
            value = float(self.thr_value.text())
        except ValueError:
            self.progress.setText("阈值数值无效")
            return
        self._rule = monitor.ThresholdRule(
            metric=self.thr_metric.text(),
            op=self.thr_op.currentText(),
            value=value,
            severity=self.thr_sev.currentText(),
        )
        self.progress.setText(f"阈值已应用: {self._rule.op} {value} -> {self._rule.severity}")

    def _on_result(self, payload: dict) -> None:
        results = payload.get("results", [])
        self.table.setRowCount(len(results))
        self.progress.setText(
            f"轮询 #{payload.get('loop', 0)}  返回 {len(results)} 项"
            + ("（持续中）" if payload.get("continuous") else "")
        )
        for i, item in enumerate(results):
            name = item["oid"]
            value = item["value"]
            status = self._status_for(value)
            self.table.setItem(i, 0, QTableWidgetItem(name))
            self.table.setItem(i, 1, QTableWidgetItem(value))
            cell = QTableWidgetItem(status)
            cell.setForeground(_STATUS_COLORS.get(status, QColor("#000000")))
            self.table.setItem(i, 2, cell)

    def _on_error(self, msg: str) -> None:
        self.progress.setText(f"错误: {msg}")

    def _status_for(self, value: str) -> str:
        if self._rule is None:
            return "ok"
        try:
            num = float(value)
        except (TypeError, ValueError):
            return "warn"
        return monitor.evaluate(num, self._rule)

    # -- Syslog --
    def _toggle_syslog(self, state: int) -> None:
        if state == Qt.Checked:
            try:
                port = int(self.syslog_port.text())
            except ValueError:
                self.progress.setText("Syslog 端口无效")
                self.syslog_toggle.setChecked(False)
                return
            self._syslog = monitor.SyslogReceiver(port=port, on_message=self._on_syslog)
            try:
                self._syslog.start()
            except RuntimeError as exc:
                self.progress.setText(str(exc))
                self.syslog_toggle.setChecked(False)
                return
            self.progress.setText(f"Syslog 监听 :{port}")
        else:
            if self._syslog:
                self._syslog.stop()
                self._syslog = None
            self.progress.setText("Syslog 已关闭")

    def _on_syslog(self, parsed: dict) -> None:
        fac = parsed.get("facility")
        sev = parsed.get("severity")
        line = f"[{parsed.get('ts')}] {parsed.get('host')} pri=<{fac},{sev}> {parsed.get('msg')}"
        item = QListWidgetItem(line)
        if isinstance(sev, int):
            if sev <= 2:
                item.setForeground(_STATUS_COLORS["crit"])
            elif sev <= 4:
                item.setForeground(_STATUS_COLORS["warn"])
        self.syslog_list.addItem(item)
        if self.syslog_list.count() > 500:
            self.syslog_list.takeItem(0)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._syslog:
            self._syslog.stop()
        super().closeEvent(event)
