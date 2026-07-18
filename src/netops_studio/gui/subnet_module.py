"""子网计算器模块（gui/subnet_module.py）。对应 core/subnet.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ..core.subnet import calculate, subnet_split, ip_in_network


class SubnetModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.cidr = QLineEdit("192.168.1.0/24")
        form.addRow("CIDR / IP", self.cidr)
        root.addLayout(form)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("计算")
        self.run_btn.clicked.connect(self._calc)
        self.split_btn = QPushButton("拆分为 /26")
        self.split_btn.clicked.connect(self._split)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.split_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        root.addWidget(self.out)

    def _calc(self) -> None:
        try:
            r = calculate(self.cidr.text())
            lines = [
                f"网络地址 : {r.network}/{r.prefixlen}",
                f"广播地址 : {r.broadcast}",
                f"子网掩码 : {r.netmask}",
                f"通配符   : {r.wildcard}",
                f"地址总数 : {r.host_count}",
                f"可用主机 : {r.usable}",
                f"首可用   : {r.first_host}",
                f"末可用   : {r.last_host}",
            ]
            self.out.setPlainText("\n".join(lines))
        except Exception as exc:  # noqa: BLE001
            self.out.setPlainText(f"错误：{exc}")

    def _split(self) -> None:
        try:
            subs = subnet_split(self.cidr.text(), 26)
            self.out.setPlainText("\n".join(f"{s.network}/{s.prefixlen}  ({s.usable} 可用)" for s in subs))
        except Exception as exc:  # noqa: BLE001
            self.out.setPlainText(f"错误：{exc}")
