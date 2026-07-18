"""安全管理模块（gui/security_module.py）。对应 core/security.py。"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import security


class SecurityJob(JobBase):
    """后台线程执行安全管理任务（协作式取消）。"""

    def __init__(self, op: str, **params: object) -> None:
        super().__init__()
        self.op = op
        self.params = params

    def run_job(self) -> None:
        if self.op == "端口审计":
            res = security.audit_ports(self.params["target"], self.params["ports"])
            self.signals.result.emit((self.op, res))
        elif self.op == "弱口令检查":
            res = security.check_password_strength(self.params["password"])
            self.signals.result.emit((self.op, res))
        elif self.op == "证书检查":
            res = security.parse_cert_expiry(self.params["cert"])
            self.signals.result.emit((self.op, res))
        elif self.op == "CVE查询":
            res = security.lookup_cve(self.params["product"])
            self.signals.result.emit((self.op, res))
        elif self.op == "防火墙审计":
            res = security.audit_firewall(self.params["config"])
            self.signals.result.emit((self.op, res))
        else:
            raise ValueError(f"未知操作：{self.op}")


class SecurityModule(QWidget):
    """安全管理模块（对应 core/security.py）。

    提供五类安全检查：端口审计、弱口令检查、证书过期检查、CVE 查询、防火墙规则审计。
    任务经 AsyncWorker 后台执行，结果按类型自适应渲染到统一表格与原始文本区。
    通过 ``sender().text()`` 区分点击了哪个按钮以决定操作。
    """

    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)

        # ---- 输入区 ----
        form = QFormLayout()
        self.target = QLineEdit("127.0.0.1")
        self.ports = QLineEdit("22,80,443,3306,3389")
        self.password = QLineEdit("")
        self.cert = QPlainTextEdit()
        self.cert.setPlaceholderText("粘贴 PEM 证书文本（-----BEGIN CERTIFICATE----- ...）")
        self.product = QLineEdit("")
        self.product.setPlaceholderText("例如 log4j / smb / openssl")
        self.fw_config = QPlainTextEdit()
        self.fw_config.setPlaceholderText("粘贴类 Cisco ACL 配置文本用于审计")

        form.addRow("目标主机", self.target)
        form.addRow("端口列表", self.ports)
        form.addRow("口令（弱口令检查）", self.password)
        form.addRow("CVE 产品", self.product)
        form.addRow("证书 (PEM)", self.cert)
        form.addRow("防火墙配置", self.fw_config)
        root.addLayout(form)

        # ---- 按钮区 ----
        btn_row = QHBoxLayout()
        self.btn_port = QPushButton("端口审计")
        self.btn_pw = QPushButton("弱口令检查")
        self.btn_cert = QPushButton("证书检查")
        self.btn_cve = QPushButton("CVE查询")
        self.btn_fw = QPushButton("防火墙审计")
        self.stop_btn = QPushButton("停止")
        for b in (self.btn_port, self.btn_pw, self.btn_cert, self.btn_cve, self.btn_fw):
            b.clicked.connect(self._run)
        self.stop_btn.clicked.connect(self.worker.cancel)
        btn_row.addWidget(self.btn_port)
        btn_row.addWidget(self.btn_pw)
        btn_row.addWidget(self.btn_cert)
        btn_row.addWidget(self.btn_cve)
        btn_row.addWidget(self.btn_fw)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.progress = QLabel("就绪")
        root.addWidget(self.progress)

        # ---- 结果展示：表格 + 文本 ----
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["字段", "值"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        root.addWidget(self.raw)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        """根据触发按钮的文字决定操作，采集对应参数并提交后台任务。"""
        sender = self.sender()
        op = sender.text() if sender is not None else ""
        self.table.setRowCount(0)
        self.raw.clear()
        self.progress.setText(f"正在执行：{op}")

        params: dict = {}
        if op == "端口审计":
            params = {"target": self.target.text().strip(),
                      "ports": self.ports.text().strip() or "1-1024"}
        elif op == "弱口令检查":
            params = {"password": self.password.text()}
        elif op == "证书检查":
            params = {"cert": self.cert.toPlainText()}
        elif op == "CVE查询":
            params = {"product": self.product.text().strip()}
        elif op == "防火墙审计":
            params = {"config": self.fw_config.toPlainText()}
        else:
            return

        job = SecurityJob(op, **params)
        self.worker.submit(job, on_result=self._show, on_error=self._err)

    def _err(self, msg: str) -> None:
        """错误回调：标记出错并展示异常信息。"""
        self.progress.setText("出错")
        self.raw.setPlainText(msg)

    # ------------------------------------------------------------------
    def _show(self, payload) -> None:
        """结果分发：解包 (op, res) 并委派给对应的渲染方法。"""
        op, res = payload
        self.progress.setText(f"完成：{op}")
        self.raw.clear()

        if op == "端口审计":
            self._show_port_audit(res)
        elif op == "弱口令检查":
            self._show_pw(res)
        elif op == "证书检查":
            self._show_cert(res)
        elif op == "CVE查询":
            self._show_cve(res)
        elif op == "防火墙审计":
            self._show_fw(res)

    def _set_rows(self, rows) -> None:
        """以「字段/值」双列表渲染一组键值对。"""
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["字段", "值"])
        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(k)))
            self.table.setItem(i, 1, QTableWidgetItem(str(v)))

    def _show_port_audit(self, res) -> None:
        """渲染端口审计结果（端口/状态/服务 + 汇总文本）。"""
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["端口", "状态", "服务"])
        self.table.setRowCount(len(res.results))
        for i, r in enumerate(res.results):
            self.table.setItem(i, 0, QTableWidgetItem(str(r.port)))
            self.table.setItem(i, 1, QTableWidgetItem(r.state))
            self.table.setItem(i, 2, QTableWidgetItem(r.service))
        self.raw.setPlainText(
            f"目标: {res.target}\n扫描端口数: {res.total}\n"
            f"开放端口: {res.open_ports if res.open_ports else '无'}"
        )

    def _show_pw(self, res) -> None:
        """渲染弱口令检查结果（评分/是否弱口令/问题项，res 为 dict）。"""
        self._set_rows([
            ("强度评分", f"{res['score']} / 100"),
            ("是否弱口令", "是" if res["score"] == 0 and res["issues"] else "否"),
            ("问题项", "\n".join(res["issues"]) if res["issues"] else "无明显问题"),
        ])

    def _show_cert(self, res) -> None:
        """渲染证书检查结果（类型/到期/剩余天数/状态）。"""
        self._set_rows([
            ("证书类型", res.type),
            ("到期时间", res.not_after.strftime("%Y-%m-%d %H:%M:%S %Z")),
            ("剩余天数", res.days_left),
            ("状态", "已过期" if res.days_left < 0 else ("即将过期" if res.days_left < 30 else "正常")),
        ])

    def _show_cve(self, res) -> None:
        """渲染 CVE 查询结果（表格 + 文本）；无结果时给出提示。"""
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["CVE", "产品", "严重度", "摘要"])
        self.table.setRowCount(len(res))
        if not res:
            self.raw.setPlainText("未查询到匹配的 CVE 记录。")
            return
        for i, r in enumerate(res):
            self.table.setItem(i, 0, QTableWidgetItem(r.get("cve_id", "")))
            self.table.setItem(i, 1, QTableWidgetItem(str(r.get("product", ""))))
            self.table.setItem(i, 2, QTableWidgetItem(str(r.get("severity", ""))))
            self.table.setItem(i, 3, QTableWidgetItem(r.get("summary", "")))
        self.raw.setPlainText("\n".join(
            f"{r.get('cve_id', '')} [{r.get('severity', '')}] {r.get('product', '')} "
            f"cvss={r.get('cvss', '')} fixed_in={r.get('fixed_in', '')}"
            for r in res
        ))

    def _show_fw(self, res) -> None:
        """渲染防火墙审计结果（统计指标 + 违规明细）。"""
        self._set_rows([
            ("规则总数", res.total),
            ("违规项数", len(res.violations)),
            ("冗余/遮蔽规则数", len(res.unused)),
        ])
        self.raw.setPlainText(
            "\n".join(res.violations) if res.violations else "未发现明显违规。"
        )
