"""子网计算器模块（gui/subnet_module.py）。对应 core/subnet.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QTextEdit, QVBoxLayout, QWidget,
)

from ..core.subnet import calculate, subnet_split
from .widgets import Card, GhostButton, PrimaryButton, SectionTitle


class SubnetModule(QWidget):
    """子网计算与拆分模块。

    对应 core/subnet.py：``calculate()`` 解析单个 CIDR 返回网络信息对象，
    ``subnet_split()`` 按新前缀长度拆分为多个子网。UI 仅负责输入采集与结果
    渲染，所有计算在调用线程同步完成（计算量小，无需异步）。
    """

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel("子网计算器")
        t.setProperty("role", "title")
        s = QLabel("CIDR 解析、地址范围、子网拆分")
        s.setProperty("role", "subtitle")
        head.addWidget(t)
        head.addWidget(s)
        root.addLayout(head)

        card = Card()
        card.body.addWidget(SectionTitle("输入"))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.cidr = QLineEdit("192.168.1.0/24")
        form.addRow("CIDR / IP", self.cidr)
        card.body.addLayout(form)

        btn_row = QHBoxLayout()
        self.run_btn = PrimaryButton("计算")
        self.run_btn.clicked.connect(self._calc)
        self.split_btn = GhostButton("拆分为 /26")
        self.split_btn.clicked.connect(self._split)
        btn_row.addWidget(self.run_btn)
        btn_row.addWidget(self.split_btn)
        btn_row.addStretch()
        card.body.addLayout(btn_row)
        root.addWidget(card)

        out_card = Card()
        out_card.body.addWidget(SectionTitle("结果"))
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        out_card.body.addWidget(self.out, 1)
        root.addWidget(out_card, 1)

    def _calc(self) -> None:
        """调用 core.subnet.calculate 解析 CIDR，并将网络信息格式化输出到结果框。"""
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
        """调用 core.subnet.subnet_split 将原网段拆分为 /26 子网并列出可用数。"""
        try:
            subs = subnet_split(self.cidr.text(), 26)
            self.out.setPlainText("\n".join(f"{s.network}/{s.prefixlen}  ({s.usable} 可用)" for s in subs))
        except Exception as exc:  # noqa: BLE001
            self.out.setPlainText(f"错误：{exc}")
