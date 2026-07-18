"""IP 地址管理模块（gui/ipam_module.py）。对应 core/ipam.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker, bus
from ..app.async_worker import JobBase
from ..core import discovery
from ..core.ipam import (
    IpamStore, allocate, detect_conflicts, reconcile, release, utilization,
)


class ReconcileJob(JobBase):
    """走 AsyncWorker 扫描网段，回传存活主机列表。"""

    def __init__(self, cidr: str) -> None:
        super().__init__()
        self.cidr = cidr

    def run_job(self) -> None:
        hosts = discovery.scan_network(
            self.cidr,
            on_progress=lambda d, t: self.signals.progress.emit(d, t),
        )
        self.signals.result.emit(hosts)


class IpamModule(QWidget):
    """IP 地址管理模块（对应 core/ipam.py）。

    管理子网增删、IP 分配/释放、利用率展示，并提供「与发现对账」：后台扫描网段
    得到存活主机，再调用 core 的 reconcile/detect_conflicts 计算差异与冲突。
    所有表格由 ``_refresh*`` 系列方法统一刷新。对账结果 publish ``ipam.reconcile``
    事件。
    """

    def __init__(self) -> None:
        super().__init__()
        self.store = IpamStore()
        self.worker = AsyncWorker()
        self._discovered: list = []  # 最近一次发现结果，用于冲突视图

        root = QVBoxLayout(self)

        # ---- 子网管理：新增 ----
        add_form = QFormLayout()
        self.cidr_input = QLineEdit("192.168.1.0/24")
        add_form.addRow("新增子网 CIDR", self.cidr_input)
        add_row = QHBoxLayout()
        add_row.addLayout(add_form)
        self.add_btn = QPushButton("添加子网")
        self.add_btn.clicked.connect(self._add_subnet)
        add_row.addWidget(self.add_btn)
        add_row.addStretch()
        root.addLayout(add_row)

        # ---- 子网表格（CIDR / 利用率条）----
        self.subnet_table = QTableWidget(0, 2)
        self.subnet_table.setHorizontalHeaderLabels(["CIDR", "利用率"])
        self.subnet_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.subnet_table)

        # ---- 分配表单 ----
        alloc_form = QFormLayout()
        self.sub_select = QComboBox()
        self.owner_input = QLineEdit()
        self.note_input = QLineEdit()
        alloc_form.addRow("选择子网", self.sub_select)
        alloc_form.addRow("所有者", self.owner_input)
        alloc_form.addRow("备注", self.note_input)
        root.addLayout(alloc_form)

        btn_row = QHBoxLayout()
        self.alloc_btn = QPushButton("分配")
        self.alloc_btn.clicked.connect(self._allocate)
        self.release_btn = QPushButton("释放")
        self.release_btn.clicked.connect(self._release)
        self.reconcile_btn = QPushButton("与发现对账")
        self.reconcile_btn.clicked.connect(self._reconcile)
        btn_row.addWidget(self.alloc_btn)
        btn_row.addWidget(self.release_btn)
        btn_row.addWidget(self.reconcile_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.bar = QProgressBar()
        root.addWidget(self.bar)

        # ---- 分配明细表 ----
        self.alloc_table = QTableWidget(0, 5)
        self.alloc_table.setHorizontalHeaderLabels(["子网", "IP", "所有者", "备注", "状态"])
        self.alloc_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.alloc_table)

        # ---- 冲突视图 ----
        self.conflict_table = QTableWidget(0, 4)
        self.conflict_table.setHorizontalHeaderLabels(["子网", "IP", "所有者", "原因"])
        self.conflict_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.conflict_table)

        self._refresh()

    # ---- 刷新 ----
    def _refresh(self) -> None:
        """统一刷新子网、分配明细、冲突三块视图。"""
        self._refresh_subnets()
        self._refresh_allocations()
        self._refresh_conflicts()

    def _refresh_subnets(self) -> None:
        """渲染子网表（CIDR + 利用率进度条）并重建子网下拉选项。"""
        subs = self.store.data["subnets"]
        self.subnet_table.setRowCount(len(subs))
        self.sub_select.clear()
        for i, sub in enumerate(subs):
            self.subnet_table.setItem(i, 0, QTableWidgetItem(sub["cidr"]))
            pct = utilization(sub["cidr"], self.store)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(int(round(pct)))
            bar.setFormat(f"{pct:.1f}%")
            self.subnet_table.setCellWidget(i, 1, bar)
            self.sub_select.addItem(sub["cidr"])

    def _refresh_allocations(self) -> None:
        """渲染所有子网下已分配 IP 的明细（含所有者/备注/状态）。"""
        rows = []
        for sub in self.store.data["subnets"]:
            for a in sub["allocations"]:
                rows.append((sub["cidr"], a.get("ip", ""), a.get("owner", ""),
                             a.get("note", ""), a.get("status", "")))
        self.alloc_table.setRowCount(len(rows))
        for i, (c, ip, o, n, s) in enumerate(rows):
            self.alloc_table.setItem(i, 0, QTableWidgetItem(c))
            self.alloc_table.setItem(i, 1, QTableWidgetItem(ip))
            self.alloc_table.setItem(i, 2, QTableWidgetItem(o))
            self.alloc_table.setItem(i, 3, QTableWidgetItem(n))
            self.alloc_table.setItem(i, 4, QTableWidgetItem(s))

    def _refresh_conflicts(self) -> None:
        """渲染冲突视图：调用 core.detect_conflicts 比对 store 与最近发现结果。"""
        conflicts = detect_conflicts(self.store, self._discovered)
        self.conflict_table.setRowCount(len(conflicts))
        for i, c in enumerate(conflicts):
            self.conflict_table.setItem(i, 0, QTableWidgetItem(c.get("cidr", "")))
            self.conflict_table.setItem(i, 1, QTableWidgetItem(c.get("ip", "")))
            self.conflict_table.setItem(i, 2, QTableWidgetItem(c.get("owner", "")))
            self.conflict_table.setItem(i, 3, QTableWidgetItem(c.get("reason", "")))

    # ---- 操作 ----
    def _add_subnet(self) -> None:
        """向 store 新增子网并刷新；失败信息写入进度条格式位。"""
        try:
            self.store.add_subnet(self.cidr_input.text())
            self._refresh()
        except Exception as exc:  # noqa: BLE001
            self.bar.setFormat(f"错误：{exc}")

    def _allocate(self) -> None:
        """在当前子网中分配一个 IP 给指定所有者。"""
        cidr = self.sub_select.currentText()
        if not cidr:
            return
        try:
            ip = allocate(self.store, cidr, self.owner_input.text(), self.note_input.text())
            self._refresh()
            self.bar.setFormat(f"已分配 {ip}")
        except Exception as exc:  # noqa: BLE001
            self.bar.setFormat(f"错误：{exc}")

    def _release(self) -> None:
        """释放表格中所选行的 IP。"""
        row = self.alloc_table.currentRow()
        if row < 0:
            return
        cidr = self.alloc_table.item(row, 0).text()
        ip = self.alloc_table.item(row, 1).text()
        try:
            release(self.store, cidr, ip)
            self._refresh()
        except Exception as exc:  # noqa: BLE001
            self.bar.setFormat(f"错误：{exc}")

    def _reconcile(self) -> None:
        """提交对账任务：先进度条置为「忙碌态」（range 0,0），后台扫描网段。"""
        cidr = self.sub_select.currentText()
        if not cidr:
            return
        self.bar.setRange(0, 0)
        job = ReconcileJob(cidr)
        self.worker.submit(job, on_result=self._on_reconcile_done, on_progress=self._on_prog)

    def _on_prog(self, done: int, total: int) -> None:
        """进度回调：重置进度条范围并反映扫描进度。"""
        self.bar.setRange(0, total)
        self.bar.setValue(done)

    def _on_reconcile_done(self, hosts) -> None:
        """结果回调：整理存活主机并 reconcile，刷新视图并广播事件。"""
        self._discovered = [{"ip": h.ip, "mac": h.mac, "status": h.state} for h in hosts]
        summary = reconcile(self.store, self._discovered)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.bar.setFormat(f"在线 {summary['online']} / 离线 {summary['offline']}（变更 {len(summary['changes'])}）")
        self._refresh()
        bus.publish("ipam.reconcile", summary)
