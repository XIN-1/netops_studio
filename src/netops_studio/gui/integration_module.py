"""集成与 API 模块（gui/integration_module.py）。对应 core/integration.py。

功能：启动/停止本地 API 服务并显示地址、设备库 CSV/JSON 导入导出、外部系统连接测试。
API 服务走 core 内部后台线程（start_api/stop_api）；外部系统测试走 AsyncWorker + JobBase。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import integration
from ..core.discovery import Host


# --------------------------------------------------------------------------
# 后台任务：外部系统连接测试（AsyncWorker + JobBase）
# --------------------------------------------------------------------------
class ConnTestJob(JobBase):
    """外部系统连接测试任务（Zabbix/Prometheus/NetBox）。

    在后台线程构造对应 client 并拉取主机列表，回传数量与前 3 条样本。
    """

    def __init__(self, kind: str, url: str, token: str, user: str = "") -> None:
        super().__init__()
        self.kind = kind
        self.url = url
        self.token = token
        self.user = user

    def run_job(self) -> None:
        if self.kind == "Zabbix":
            client = integration.ZabbixClient(self.url, self.user, self.token)
        elif self.kind == "Prometheus":
            client = integration.PrometheusClient(self.url)
        else:
            client = integration.NetBoxClient(self.url, self.token)
        hosts = client.get_hosts()
        self.signals.result.emit({"count": len(hosts), "sample": hosts[:3]})


class IntegrationModule(QWidget):
    """集成与 API 模块（对应 core/integration.py）。

    包含三块能力：(1) 本地 API 服务启停（core 内置后台线程）；
    (2) 设备库 CSV/JSON 导入导出（本地纯函数）；
    (3) 外部系统（Zabbix/Prometheus/NetBox）连接测试（AsyncWorker 后台执行）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        self.devices: List[Host] = []
        root = QVBoxLayout(self)

        # ---- 1. 本地 API 服务 ----
        api_box = QGroupBox("本地 API 服务")
        api_layout = QFormLayout(api_box)
        self.api_host = QLineEdit("127.0.0.1")
        self.api_port = QLineEdit("8000")
        api_layout.addRow("监听地址", self.api_host)
        api_layout.addRow("端口", self.api_port)

        api_btn = QHBoxLayout()
        self.api_start = QPushButton("启动")
        self.api_start.clicked.connect(self._start_api)
        self.api_stop = QPushButton("停止")
        self.api_stop.clicked.connect(self._stop_api)
        self.api_stop.setEnabled(False)
        api_btn.addWidget(self.api_start)
        api_btn.addWidget(self.api_stop)
        api_btn.addStretch()
        api_layout.addRow(api_btn)

        self.api_status = QLabel("状态：未运行")
        api_layout.addRow(self.api_status)
        root.addWidget(api_box)

        # ---- 2. 设备库导入/导出 ----
        dev_box = QGroupBox("设备库（CSV / JSON）")
        dev_layout = QVBoxLayout(dev_box)
        dev_btn = QHBoxLayout()
        self.btn_import_csv = QPushButton("导入 CSV")
        self.btn_import_json = QPushButton("导入 JSON")
        self.btn_export_csv = QPushButton("导出 CSV")
        self.btn_export_json = QPushButton("导出 JSON")
        self.btn_import_csv.clicked.connect(lambda: self._import("csv"))
        self.btn_import_json.clicked.connect(lambda: self._import("json"))
        self.btn_export_csv.clicked.connect(lambda: self._export("csv"))
        self.btn_export_json.clicked.connect(lambda: self._export("json"))
        for b in (self.btn_import_csv, self.btn_import_json,
                  self.btn_export_csv, self.btn_export_json):
            dev_btn.addWidget(b)
        dev_btn.addStretch()
        dev_layout.addLayout(dev_btn)

        self.dev_table = QTableWidget(0, 6)
        self.dev_table.setHorizontalHeaderLabels(
            ["IP", "主机名", "MAC", "厂商", "状态", "延迟(ms)"])
        self.dev_table.horizontalHeader().setStretchLastSection(True)
        dev_layout.addWidget(self.dev_table)

        self.dev_raw = QTextEdit()
        self.dev_raw.setReadOnly(True)
        self.dev_raw.setPlaceholderText("导入/导出结果预览…")
        dev_layout.addWidget(self.dev_raw)
        root.addWidget(dev_box)

        # ---- 3. 外部系统连接测试 ----
        ext_box = QGroupBox("外部系统连接测试")
        ext_layout = QFormLayout(ext_box)
        self.ext_kind = QComboBox()
        self.ext_kind.addItems(["Zabbix", "Prometheus", "NetBox"])
        self.ext_url = QLineEdit("")
        self.ext_user = QLineEdit("")
        self.ext_token = QLineEdit("")
        self.ext_token.setEchoMode(QLineEdit.Password)
        ext_layout.addRow("系统类型", self.ext_kind)
        ext_layout.addRow("URL", self.ext_url)
        ext_layout.addRow("用户名(Zabbix)", self.ext_user)
        ext_layout.addRow("Token / API Key", self.ext_token)

        ext_btn = QHBoxLayout()
        self.ext_test = QPushButton("测试连接")
        self.ext_test.clicked.connect(self._test_conn)
        self.ext_cancel = QPushButton("停止")
        self.ext_cancel.clicked.connect(self.worker.cancel)
        ext_btn.addWidget(self.ext_test)
        ext_btn.addWidget(self.ext_cancel)
        ext_btn.addStretch()
        ext_layout.addRow(ext_btn)

        self.ext_status = QLabel("状态：待测试")
        ext_layout.addRow(self.ext_status)
        root.addWidget(ext_box)

    # ---- API 服务 ----
    def _start_api(self) -> None:
        """校验端口后启动本地 API 服务并切换按钮状态。"""
        host = self.api_host.text().strip() or "127.0.0.1"
        try:
            port = int(self.api_port.text().strip() or "8000")
        except ValueError:
            self.api_status.setText("状态：端口必须为整数")
            return
        try:
            info = integration.start_api(host, port)
        except RuntimeError as exc:
            self.api_status.setText(f"状态：{exc}")
            return
        self.api_status.setText(f"状态：运行中 {info['url']}")
        self.api_start.setEnabled(False)
        self.api_stop.setEnabled(True)

    def _stop_api(self) -> None:
        """停止本地 API 服务并恢复按钮状态。"""
        stopped = integration.stop_api()
        self.api_status.setText("状态：已停止" if stopped else "状态：本未运行")
        self.api_start.setEnabled(True)
        self.api_stop.setEnabled(False)

    # ---- 设备库 ----
    def _render_devices(self) -> None:
        """将已加载的设备列表渲染到表格（含延迟，None 显示为空白）。"""
        self.dev_table.setRowCount(len(self.devices))
        for i, h in enumerate(self.devices):
            self.dev_table.setItem(i, 0, QTableWidgetItem(h.ip))
            self.dev_table.setItem(i, 1, QTableWidgetItem(h.hostname))
            self.dev_table.setItem(i, 2, QTableWidgetItem(h.mac))
            self.dev_table.setItem(i, 3, QTableWidgetItem(h.vendor))
            self.dev_table.setItem(i, 4, QTableWidgetItem(h.state))
            lat = "" if h.latency_ms is None else str(h.latency_ms)
            self.dev_table.setItem(i, 5, QTableWidgetItem(lat))

    def _import(self, fmt: str) -> None:
        """导入设备库文件（csv/json）并预览转换后的文本。"""
        path, _ = QFileDialog.getOpenFileName(
            self, f"导入设备库（{fmt.upper()}）", "",
            "CSV 文件 (*.csv)" if fmt == "csv" else "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            self.devices = (integration.csv_to_devices(text) if fmt == "csv"
                            else integration.json_to_devices(text))
        except Exception as exc:  # noqa: BLE001
            self.dev_raw.setPlainText(f"导入失败：{exc}")
            return
        self._render_devices()
        self.dev_raw.setPlainText(
            f"已导入 {len(self.devices)} 条设备\n\n" +
            (integration.devices_to_csv(self.devices)
             if fmt == "csv" else integration.devices_to_json(self.devices)))

    def _export(self, fmt: str) -> None:
        """将当前设备列表导出为 csv/json 文件。"""
        if not self.devices:
            self.dev_raw.setPlainText("无设备可导出")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出设备库（{fmt.upper()}）", "",
            "CSV 文件 (*.csv)" if fmt == "csv" else "JSON 文件 (*.json)")
        if not path:
            return
        text = (integration.devices_to_csv(self.devices) if fmt == "csv"
                else integration.devices_to_json(self.devices))
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as exc:  # noqa: BLE001
            self.dev_raw.setPlainText(f"导出失败：{exc}")
            return
        self.dev_raw.setPlainText(f"已导出 {len(self.devices)} 条设备至 {path}")

    # ---- 外部系统连接测试 ----
    def _test_conn(self) -> None:
        """提交外部系统连接测试任务。"""
        self.ext_status.setText("状态：测试中…")
        job = ConnTestJob(
            self.ext_kind.currentText(),
            self.ext_url.text().strip(),
            self.ext_token.text().strip(),
            self.ext_user.text().strip(),
        )
        self.worker.submit(job, on_result=self._conn_done, on_error=self._conn_err)

    def _conn_done(self, res: dict) -> None:
        """连接测试成功回调：展示获取到主机数量。"""
        self.ext_status.setText(f"状态：成功，获取 {res['count']} 台主机")

    def _conn_err(self, msg: str) -> None:
        """连接测试失败回调：展示异常信息。"""
        self.ext_status.setText(f"状态：失败 - {msg}")
