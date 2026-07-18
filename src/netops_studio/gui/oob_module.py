"""带外与机房模块（gui/oob_module.py）。对应 core/outofband.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import outofband


class OobJob(JobBase):
    """后台执行带外/机房操作（网络 IO），结果以 dict 回传。"""

    def __init__(self, op: str, **kwargs: object) -> None:
        super().__init__()
        self.op = op
        self.kwargs = kwargs

    def run_job(self) -> None:
        if self.op == "redfish":
            text = outofband.get_chassis(
                self.kwargs["url"], self.kwargs["user"], self.kwargs["pwd"]
            )
            self.signals.result.emit({"op": "redfish", "data": outofband.parse_redfish(text)})
        elif self.op == "ipmitool":
            text = outofband.get_sensors(
                self.kwargs["host"], self.kwargs["user"], self.kwargs["pwd"]
            )
            self.signals.result.emit({"op": "ipmitool", "data": outofband.parse_ipmitool(text)})
        elif self.op == "env":
            text = outofband.get_sensors(
                self.kwargs["host"], self.kwargs["user"], self.kwargs["pwd"]
            )
            self.signals.result.emit({"op": "env", "data": outofband.parse_env(text)})
        elif self.op == "pdu_rest":
            self.signals.result.emit(
                {"op": "pdu", "data": outofband.pdu_control_rest(**self.kwargs)}
            )
        elif self.op == "pdu_snmp":
            self.signals.result.emit(
                {"op": "pdu", "data": outofband.pdu_control_snmp(**self.kwargs)}
            )
        else:
            raise ValueError(f"未知操作：{self.op}")


class OobModule(QWidget):
    """带外与机房模块（对应 core/outofband.py）。

    两块能力：(1) 带外遥测——Redfish / ipmitool 传感器、温湿度、PDU 控制（经
    AsyncWorker 后台执行，统一以 key/value 表格渲染）；(2) 机架管理——本地
    RackStore 持久化的机架/设备增删（直接操作，无需后台线程）。
    """

    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        self.store = outofband.RackStore()

        root = QVBoxLayout(self)
        tabs = QTabWidget()
        root.addWidget(tabs)

        # ---- 带外遥测 ----
        telemetry = QWidget()
        tlay = QVBoxLayout(telemetry)
        tabs.addTab(telemetry, "带外遥测")

        form = QFormLayout()
        self.proto = QComboBox()
        self.proto.addItems(["Redfish (iDRAC)", "ipmitool (LAN+)"])
        self.addr = QLineEdit("192.168.1.100")
        self.user = QLineEdit("root")
        self.pwd = QLineEdit("")
        self.pwd.setEchoMode(QLineEdit.Password)
        form.addRow("协议", self.proto)
        form.addRow("带外地址", self.addr)
        form.addRow("用户名", self.user)
        form.addRow("密码", self.pwd)
        tlay.addLayout(form)

        btn_row = QHBoxLayout()
        self.sensor_btn = QPushButton("获取传感器")
        self.env_btn = QPushButton("温湿度")
        self.pdu_rest_btn = QPushButton("PDU(REST)")
        self.pdu_snmp_btn = QPushButton("PDU(SNMP)")
        self.stop_btn = QPushButton("停止")
        for b in (self.sensor_btn, self.env_btn, self.pdu_rest_btn,
                  self.pdu_snmp_btn, self.stop_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        tlay.addLayout(btn_row)

        self.status = QLabel("就绪")
        tlay.addWidget(self.status)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["项目", "值"])
        self.table.horizontalHeader().setStretchLastSection(True)
        tlay.addWidget(self.table)

        self.raw = QTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("原始返回（Redfish JSON / ipmitool 文本）")
        tlay.addWidget(self.raw)

        # ---- 机架管理（本地持久化）----
        rack = QWidget()
        rlay = QVBoxLayout(rack)
        tabs.addTab(rack, "机架管理")

        rform = QFormLayout()
        self.rack_name = QLineEdit("RACK-A")
        self.dev_u = QLineEdit("10")
        self.dev_name = QLineEdit("core-sw1")
        self.dev_sn = QLineEdit("SN123456")
        rform.addRow("机架名", self.rack_name)
        rform.addRow("U 位", self.dev_u)
        rform.addRow("设备名", self.dev_name)
        rform.addRow("序列号", self.dev_sn)
        rlay.addLayout(rform)

        rbtn = QHBoxLayout()
        self.add_rack_btn = QPushButton("添加机架")
        self.add_dev_btn = QPushButton("添加设备")
        self.del_dev_btn = QPushButton("删除设备")
        self.del_rack_btn = QPushButton("删除机架")
        self.refresh_btn = QPushButton("刷新")
        for b in (self.add_rack_btn, self.add_dev_btn, self.del_dev_btn,
                  self.del_rack_btn, self.refresh_btn):
            rbtn.addWidget(b)
        rbtn.addStretch()
        rlay.addLayout(rbtn)

        self.rack_status = QLabel("就绪")
        rlay.addWidget(self.rack_status)

        self.rack_table = QTableWidget(0, 4)
        self.rack_table.setHorizontalHeaderLabels(["机架", "U位", "设备", "序列号"])
        self.rack_table.horizontalHeader().setStretchLastSection(True)
        rlay.addWidget(self.rack_table)

        # ---- 信号绑定 ----
        self.sensor_btn.clicked.connect(self._sensors)
        self.env_btn.clicked.connect(self._env)
        self.pdu_rest_btn.clicked.connect(self._pdu_rest)
        self.pdu_snmp_btn.clicked.connect(self._pdu_snmp)
        self.stop_btn.clicked.connect(self.worker.cancel)
        self.add_rack_btn.clicked.connect(self._add_rack)
        self.add_dev_btn.clicked.connect(self._add_device)
        self.del_dev_btn.clicked.connect(self._del_device)
        self.del_rack_btn.clicked.connect(self._del_rack)
        self.refresh_btn.clicked.connect(self._refresh_racks)

        self._refresh_racks()

    # -- 网络操作（AsyncWorker）--
    def _submit(self, op: str, **kwargs: object) -> None:
        """提交一次带外/机房后台任务并清空结果区。"""
        self.status.setText(f"执行 {op} …")
        self.raw.clear()
        self.table.setRowCount(0)
        job = OobJob(op, **kwargs)
        self.worker.submit(job, on_result=self._show, on_error=self._err)

    def _err(self, msg: str) -> None:
        """错误回调：标记错误并展示异常文本。"""
        self.status.setText("错误")
        self.raw.setPlainText(msg)

    def _sensors(self) -> None:
        """获取传感器：Redfish 协议走 redfish 分支，否则走 ipmitool 分支。"""
        if self.proto.currentText().startswith("Redfish"):
            self._submit("redfish", url=self.addr.text().strip(),
                         user=self.user.text().strip(), pwd=self.pwd.text())
        else:
            self._submit("ipmitool", host=self.addr.text().strip(),
                         user=self.user.text().strip(), pwd=self.pwd.text())

    def _env(self) -> None:
        """获取温湿度：走 env 分支（get_sensors + parse_env）。"""
        self._submit("env", host=self.addr.text().strip(),
                     user=self.user.text().strip(), pwd=self.pwd.text())

    def _pdu_rest(self) -> None:
        """PDU 控制（REST 方式，outlet 为字符串）。"""
        self._submit("pdu_rest", url=self.addr.text().strip(),
                     outlet="1", action="on")

    def _pdu_snmp(self) -> None:
        """PDU 控制（SNMP 方式，outlet 为整数）。"""
        self._submit("pdu_snmp", host=self.addr.text().strip(),
                     outlet=1, action="on")

    # -- 结果渲染（统一 key/value 表格）--
    def _show(self, res: dict) -> None:
        """结果回调：按 op（redfish/ipmitool/env/pdu）格式化展示。"""
        op = res.get("op")
        data = res.get("data")
        rows: list = []

        if op == "redfish":
            self.status.setText("Redfish 获取完成")
            health = data.get("health", "Unknown")
            rows.append(("health", str(health)))
            for k, v in (data.get("temp") or {}).items():
                rows.append((f"temp:{k}", str(v)))
            for k, v in (data.get("power") or {}).items():
                rows.append((f"power:{k}", str(v)))
            self._set_rows(rows)
            self.raw.setPlainText("（Redfish 结构见表格；原始 JSON 由引擎解析）")

        elif op == "ipmitool":
            self.status.setText(f"ipmitool 获取完成（{len(data)} 项）")
            for k, v in data.items():
                rows.append((k, str(v)))
            self._set_rows(rows)
            self.raw.setPlainText("（传感器明细见表格）")

        elif op == "env":
            self.status.setText("温湿度解析完成")
            if not data:
                self.status.setText("温湿度：未解析到数据")
            for k, v in data.items():
                rows.append((k, str(v)))
            self._set_rows(rows)
            self.raw.setPlainText("（温湿度见表格）")

        elif op == "pdu":
            self.status.setText(f"PDU({data.get('protocol')})：{data.get('status')}")
            for k, v in data.items():
                rows.append((k, str(v)))
            self._set_rows(rows)
            self.raw.setPlainText(data.get("message", ""))

    def _set_rows(self, rows: list) -> None:
        """以「项目/值」双列表渲染键值对。"""
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["项目", "值"])
        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(k)))
            self.table.setItem(i, 1, QTableWidgetItem(str(v)))

    # -- 机架管理（本地直接操作）--
    def _add_rack(self) -> None:
        """新增机架（已存在则提示）。"""
        name = self.rack_name.text().strip()
        if not name:
            self.rack_status.setText("机架名不能为空")
            return
        if self.store.add_rack(name):
            self.rack_status.setText(f"已添加机架：{name}")
        else:
            self.rack_status.setText(f"机架已存在：{name}")
        self._refresh_racks()

    def _add_device(self) -> None:
        """向指定机架添加设备（U 位须为整数）。"""
        name = self.rack_name.text().strip()
        dev = self.dev_name.text().strip()
        if not name or not dev:
            self.rack_status.setText("机架名与设备名不能为空")
            return
        try:
            u = int(self.dev_u.text().strip() or "0")
        except ValueError:
            self.rack_status.setText("U 位必须为整数")
            return
        if self.store.add_device(name, u, dev, self.dev_sn.text().strip()):
            self.rack_status.setText(f"已添加设备 {dev} 到 {name}")
        else:
            self.rack_status.setText(f"机架不存在：{name}")
        self._refresh_racks()

    def _del_device(self) -> None:
        """从指定机架删除设备。"""
        name = self.rack_name.text().strip()
        dev = self.dev_name.text().strip()
        if not name or not dev:
            self.rack_status.setText("机架名与设备名不能为空")
            return
        if self.store.remove_device(name, dev):
            self.rack_status.setText(f"已删除设备 {dev}")
        else:
            self.rack_status.setText("未找到设备")
        self._refresh_racks()

    def _del_rack(self) -> None:
        """删除指定机架。"""
        name = self.rack_name.text().strip()
        if not name:
            self.rack_status.setText("机架名不能为空")
            return
        if self.store.remove_rack(name):
            self.rack_status.setText(f"已删除机架：{name}")
        else:
            self.rack_status.setText("未找到机架")
        self._refresh_racks()

    def _refresh_racks(self) -> None:
        """渲染机架-设备表格（机架/ U 位/ 设备/ 序列号）。"""
        rows: list = []
        for r in self.store.racks:
            rack = r.get("name", "")
            for d in r.get("devices", []):
                rows.append((rack, str(d.get("u", "")), d.get("name", ""),
                             d.get("sn", "")))
        self.rack_table.setColumnCount(4)
        self.rack_table.setHorizontalHeaderLabels(["机架", "U位", "设备", "序列号"])
        self.rack_table.setRowCount(len(rows))
        for i, (a, b, c, d) in enumerate(rows):
            self.rack_table.setItem(i, 0, QTableWidgetItem(a))
            self.rack_table.setItem(i, 1, QTableWidgetItem(b))
            self.rack_table.setItem(i, 2, QTableWidgetItem(c))
            self.rack_table.setItem(i, 3, QTableWidgetItem(d))
