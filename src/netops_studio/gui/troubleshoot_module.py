"""专项排障模块（gui/troubleshoot_module.py）。对应 core/troubleshoot.py。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import troubleshoot

_PASTE_TYPE_MAP = {"ARP 表": "arp", "STP": "stp", "DHCP 池": "dhcp"}


class TroubleshootJob(JobBase):
    """后台线程执行排障（协作式取消）。携带操作类型与参数，run_job 内做网络采集/本地解析。"""

    def __init__(self, op: str, device: str, creds: dict, vendor: str,
                 paste_text: str = "", paste_type: str = "arp") -> None:
        super().__init__()
        self.op = op
        self.device = device
        self.creds = creds
        self.vendor = vendor
        self.paste_text = paste_text
        self.paste_type = paste_type

    def run_job(self) -> None:
        if self.op == "arp":
            self._run_arp()
        elif self.op == "stp":
            self._run_stp()
        elif self.op == "dhcp":
            self._run_dhcp()
        elif self.op == "paste":
            self._run_paste()

    # -- 实时采集 --
    def _run_arp(self) -> None:
        """采集并分析 ARP 表，输出 IP 冲突（若有）否则展示 ARP 条目。"""
        data = troubleshoot.collect_and_analyze(self.device, self.creds, self.vendor)
        conflicts = data["ip_conflicts"]
        if conflicts:
            rows = [[c["ip"], " | ".join(c["macs"]), " | ".join(c["interfaces"])]
                    for c in conflicts]
            columns = ["冲突 IP", "MAC 列表", "接口"]
            summary = f"检测到 {len(conflicts)} 处 IP 冲突"
        else:
            rows = [[e["ip"], e["mac"], e.get("interface", "")]
                    for e in data["arp_entries"]]
            columns = ["IP", "MAC", "接口"]
            summary = f"ARP 表共 {len(data['arp_entries'])} 条，未发现 IP 冲突"
        self.signals.result.emit({
            "title": "IP 冲突检测", "columns": columns, "rows": rows,
            "raw": data["arp_raw"], "summary": summary,
        })

    def _run_stp(self) -> None:
        """采集并分析 STP，输出异常（若有）否则展示根桥/阻塞端口。"""
        data = troubleshoot.collect_and_analyze(self.device, self.creds, self.vendor)
        anomalies = data["stp_anomalies"]
        if anomalies:
            rows = [[a["type"], a["detail"], a.get("port", "")] for a in anomalies]
            columns = ["类型", "详情", "端口/MAC"]
            summary = f"发现 {len(anomalies)} 处 STP 异常"
        else:
            stp = data["stp"]
            rows = [["根桥", stp.get("root") or "未知", ""]]
            for p in stp.get("blocked_ports", []):
                rows.append(["阻塞端口", p, ""])
            columns = ["项", "值", ""]
            summary = "STP 正常，未发现环路迹象"
        self.signals.result.emit({
            "title": "STP 环路检测", "columns": columns, "rows": rows,
            "raw": data["stp_raw"], "summary": summary,
        })

    def _run_dhcp(self) -> None:
        """采集并分析 DHCP，输出地址池冲突（若有）否则展示各地址池。"""
        data = troubleshoot.collect_dhcp(self.device, self.creds, self.vendor)
        conflicts = data["dhcp_conflicts"]
        if conflicts:
            rows = [[c.get("pool_a", ""), c.get("pool_b", ""), c.get("detail", "")]
                    for c in conflicts]
            columns = ["池 A", "池 B", "冲突详情"]
            summary = f"检测到 {len(conflicts)} 处 DHCP 冲突"
        else:
            pools = data["dhcp_pools"]
            rows = [[p.get("name", ""), p.get("network", ""), p.get("gateway", "")]
                    for p in pools]
            columns = ["地址池", "网段", "网关"]
            summary = f"DHCP 共 {len(pools)} 个地址池，未发现冲突"
        self.signals.result.emit({
            "title": "DHCP 检查", "columns": columns, "rows": rows,
            "raw": data["dhcp_raw"], "summary": summary,
        })

    # -- 粘贴输出直接分析（无需连接设备）--
    def _run_paste(self) -> None:
        """解析粘贴的 show/display 输出（arp/stp/dhcp），无需连接设备。"""
        t = self.paste_type
        raw = self.paste_text
        if t == "arp":
            entries = troubleshoot.parse_arp_table(self.vendor, raw)
            conflicts = troubleshoot.detect_ip_conflict(entries)
            rows = [[e["ip"], e["mac"], e.get("interface", "")] for e in entries]
            columns = ["IP", "MAC", "接口"]
            summary = (f"解析 ARP 共 {len(entries)} 条"
                       + (f"，发现 {len(conflicts)} 处冲突" if conflicts else "，无冲突"))
        elif t == "stp":
            info = troubleshoot.parse_spanning_tree(raw)
            rows = [["根桥", info.get("root") or "未知", ""]]
            for p in info.get("blocked_ports", []):
                rows.append(["阻塞端口", p, ""])
            anomalies = troubleshoot.detect_loop([], info)
            columns = ["项", "值", ""]
            summary = ("STP 解析完成"
                       + (f"，{len(anomalies)} 处异常" if anomalies else ""))
        else:  # dhcp
            pools = troubleshoot.parse_dhcp_pool(raw)
            conflicts = troubleshoot.detect_dhcp_conflict(pools)
            rows = [[p.get("name", ""), p.get("network", ""), p.get("gateway", "")]
                    for p in pools]
            columns = ["地址池", "网段", "网关"]
            summary = (f"解析 DHCP 池 {len(pools)} 个"
                       + (f"，{len(conflicts)} 处冲突" if conflicts else ""))
        self.signals.result.emit({
            "title": "粘贴输出分析", "columns": columns, "rows": rows,
            "raw": raw, "summary": summary,
        })


class TroubleshootModule(QWidget):
    """专项排障模块（对应 core/troubleshoot.py）。

    支持三类实时采集分析（IP 冲突/STP 环路/DHCP 检查，需连接设备）以及
    「粘贴输出分析」（无需连设备，解析 show/display 文本）。任务经 AsyncWorker
    后台执行，结果以动态列数的表格 + 原始文本区展示。
    """

    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)

        # ---- 设备连接表单 ----
        form = QFormLayout()
        self.address = QLineEdit("192.168.1.1")
        self.vendor = QComboBox()
        self.vendor.addItems(["cisco", "huawei", "h3c", "juniper"])
        self.user = QLineEdit("admin")
        self.pw = QLineEdit("")
        self.pw.setEchoMode(QLineEdit.Password)
        self.secret = QLineEdit("")
        self.secret.setEchoMode(QLineEdit.Password)
        form.addRow("设备地址", self.address)
        form.addRow("厂商", self.vendor)
        form.addRow("用户名", self.user)
        form.addRow("密码", self.pw)
        form.addRow("Enable 密文", self.secret)
        root.addLayout(form)

        # ---- 操作按钮 ----
        btn_row = QHBoxLayout()
        self.arp_btn = QPushButton("IP 冲突检测")
        self.stp_btn = QPushButton("STP 环路检测")
        self.dhcp_btn = QPushButton("DHCP 检查")
        self.paste_btn = QPushButton("粘贴输出分析")
        self.stop_btn = QPushButton("停止")
        self.arp_btn.clicked.connect(lambda: self._run_op("arp"))
        self.stp_btn.clicked.connect(lambda: self._run_op("stp"))
        self.dhcp_btn.clicked.connect(lambda: self._run_op("dhcp"))
        self.paste_btn.clicked.connect(lambda: self._run_op("paste"))
        self.stop_btn.clicked.connect(self.worker.cancel)
        for b in (self.arp_btn, self.stp_btn, self.dhcp_btn,
                  self.paste_btn, self.stop_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.progress = QLabel("就绪")
        root.addWidget(self.progress)

        # ---- 粘贴输出 + 分析类型 ----
        paste_row = QHBoxLayout()
        paste_row.addWidget(QLabel("分析类型"))
        self.paste_type = QComboBox()
        self.paste_type.addItems(list(_PASTE_TYPE_MAP.keys()))
        paste_row.addWidget(self.paste_type)
        paste_row.addStretch()
        root.addLayout(paste_row)

        self.paste = QTextEdit()
        self.paste.setPlaceholderText("在此粘贴设备 show / display 输出，选择分析类型后点击「粘贴输出分析」")
        root.addWidget(self.paste)

        # ---- 结果表格 ----
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["字段", "值", ""])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

        self.raw = QTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setPlaceholderText("原始输出 / 详情")
        root.addWidget(self.raw)

    # ------------------------------------------------------------------
    def _creds(self) -> dict:
        """从表单组装连接凭据字典（含 enable 密文 secret）。"""
        return {
            "host": self.address.text().strip(),
            "username": self.user.text().strip(),
            "password": self.pw.text(),
            "secret": self.secret.text(),
            "vendor": self.vendor.currentText(),
        }

    def _run_op(self, op: str) -> None:
        """提交排障任务；粘贴分析型操作仍走同一 Job（run_job 内分支决定行为）。"""
        self.table.setRowCount(0)
        self.raw.clear()
        self.progress.setText("正在连接设备并采集…")
        paste_type = _PASTE_TYPE_MAP.get(self.paste_type.currentText(), "arp")
        job = TroubleshootJob(
            op, self.address.text().strip(), self._creds(),
            self.vendor.currentText(),
            paste_text=self.paste.toPlainText(),
            paste_type=paste_type,
        )
        self.worker.submit(
            job,
            on_result=self._show,
            on_progress=self._prog,
            on_error=self._err,
        )

    def _prog(self, done: int, total: int) -> None:
        """进度回调：更新状态标签。"""
        self.progress.setText(f"进度 {done}/{total}")

    def _err(self, msg: str) -> None:
        """错误回调：标记错误并展示异常文本。"""
        self.progress.setText(f"错误：{msg}")
        self.raw.setPlainText(msg)

    def _show(self, result: dict) -> None:
        """结果回调：按返回的列定义与行数据动态渲染表格 + 原始文本。"""
        self.progress.setText(result.get("summary", "完成"))
        self.raw.setPlainText(result.get("raw", ""))
        cols = result.get("columns", [])
        rows = result.get("rows", [])
        self.table.setColumnCount(max(1, len(cols)))
        self.table.setHorizontalHeaderLabels(cols if cols else ["结果"])
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                self.table.setItem(i, j, QTableWidgetItem(str(val)))
