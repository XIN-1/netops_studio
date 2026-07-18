"""流量深度分析模块（gui/flow_module.py）。对应 core/flow.py。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QListWidget,
    QPushButton, QDoubleSpinBox, QLineEdit, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import flow


class FlowImportJob(JobBase):
    """后台线程载入并解析 flow 文件（协作式取消）。"""

    def __init__(self, path: str, threshold_mb: float) -> None:
        super().__init__()
        self.path = path
        self.threshold_mb = threshold_mb

    def run_job(self) -> None:
        records = flow.import_flow(self.path)
        if self.should_stop():
            return
        anomalies = flow.detect_anomalies(records, threshold_mb=self.threshold_mb)
        self.signals.result.emit({
            "path": self.path,
            "records": records,
            "anomalies": anomalies,
        })


class FlowModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        self._records = []

        root = QVBoxLayout(self)

        # ---- 导入区 ----
        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择 flow 记录文件（JSON / CSV）")
        self.browse_btn = QPushButton("浏览")
        self.browse_btn.clicked.connect(self._browse)
        self.import_btn = QPushButton("导入分析")
        self.import_btn.clicked.connect(self._import)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.worker.cancel)
        file_row.addWidget(self.path_edit)
        file_row.addWidget(self.browse_btn)
        file_row.addWidget(self.import_btn)
        file_row.addWidget(self.stop_btn)
        root.addLayout(file_row)

        # ---- 阈值 ----
        opt_row = QHBoxLayout()
        self.thr = QDoubleSpinBox()
        self.thr.setRange(0.0, 10000.0)
        self.thr.setValue(100.0)
        self.thr.setSuffix(" MB")
        self.thr.setDecimals(1)
        opt_row.addWidget(QLabel("单流突增阈值"))
        opt_row.addWidget(self.thr)
        opt_row.addStretch()
        root.addLayout(opt_row)

        self.status = QLabel("就绪")
        root.addWidget(self.status)

        # ---- 表格区：Top Talkers + 应用占比 ----
        tables = QHBoxLayout()

        self.talkers_tbl = QTableWidget(0, 3)
        self.talkers_tbl.setHorizontalHeaderLabels(["#", "端到端", "字节数"])
        self.talkers_tbl.horizontalHeader().setStretchLastSection(True)
        self.talkers_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tables.addWidget(self.talkers_tbl)

        self.share_tbl = QTableWidget(0, 3)
        self.share_tbl.setHorizontalHeaderLabels(["应用", "字节数", "占比"])
        self.share_tbl.horizontalHeader().setStretchLastSection(True)
        self.share_tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tables.addWidget(self.share_tbl)

        root.addLayout(tables)

        # ---- 异常列表 ----
        root.addWidget(QLabel("异常检测"))
        self.anomaly_list = QListWidget()
        root.addWidget(self.anomaly_list)

    # ------------------------------------------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 flow 文件", "",
            "Flow Files (*.json *.csv);;JSON (*.json);;CSV (*.csv);;All (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _import(self) -> None:
        path = self.path_edit.text().strip()
        if not path:
            self.status.setText("请先选择文件")
            return
        self.status.setText("分析中…")
        self.talkers_tbl.setRowCount(0)
        self.share_tbl.setRowCount(0)
        self.anomaly_list.clear()
        job = FlowImportJob(path, self.thr.value())
        self.worker.submit(job, on_result=self._show, on_error=self._on_error)

    def _on_error(self, msg: str) -> None:
        self.status.setText(f"错误：{msg}")

    def _show(self, res: dict) -> None:
        self._records = res.get("records", [])
        self.status.setText(f"完成：共 {len(self._records)} 条记录")
        self._render_talkers(flow.top_talkers(self._records, n=20))
        self._render_share(flow.app_share(self._records))
        self._render_anomalies(res.get("anomalies", []))

    # ------------------------------------------------------------------
    def _render_talkers(self, talkers) -> None:
        self.talkers_tbl.setRowCount(len(talkers))
        for i, r in enumerate(talkers):
            self.talkers_tbl.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.talkers_tbl.setItem(i, 1, QTableWidgetItem(r.endpoint))
            self.talkers_tbl.setItem(i, 2, QTableWidgetItem(f"{r.bytes:,}"))
        self.talkers_tbl.resizeColumnsToContents()

    def _render_share(self, share: dict) -> None:
        total = sum(share.values()) or 1
        self.share_tbl.setRowCount(len(share))
        for i, (app, b) in enumerate(share.items()):
            self.share_tbl.setItem(i, 0, QTableWidgetItem(app))
            self.share_tbl.setItem(i, 1, QTableWidgetItem(f"{b:,}"))
            self.share_tbl.setItem(i, 2, QTableWidgetItem(f"{b / total * 100:.1f}%"))
        self.share_tbl.resizeColumnsToContents()

    def _render_anomalies(self, anomalies: list) -> None:
        self.anomaly_list.clear()
        if not anomalies:
            self.anomaly_list.addItem("未发现异常")
            return
        for a in anomalies:
            self.anomaly_list.addItem(f"[{a['type']}] {a['detail']}")
