"""编解码工具模块（gui/codec_module.py）。对应 core/codec.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel, QComboBox, QFormLayout, QHBoxLayout, QTextEdit, QVBoxLayout, QWidget,
)

from ..core import codec
from .widgets import Card, PrimaryButton, SectionTitle


class CodecModule(QWidget):
    """编解码/转换工具模块（对应 core/codec.py）。

    通过下拉框选择操作（Base64/URL/哈希/进制/时间戳/JWT/PEM/Hex 等），
    按操作动态显隐算法与进制参数，点击「处理」同步调用对应 core 函数并输出结果。
    """

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel("编解码工具")
        t.setProperty("role", "title")
        s = QLabel("Base64 / URL / 哈希 / 进制 / 时间戳 / JWT / PEM")
        s.setProperty("role", "subtitle")
        head.addWidget(t)
        head.addWidget(s)
        root.addLayout(head)

        card = Card()
        card.body.addWidget(SectionTitle("操作选择"))
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.op = QComboBox()
        self.op.addItems([
            "Base64 编码", "Base64 解码", "URL 编码", "URL 解码",
            "哈希", "进制转换", "时间戳转换", "JWT 解析", "PEM 解析",
            "文本→Hex", "Hex→文本",
        ])
        self.op.currentTextChanged.connect(self._on_op)
        self.algo = QComboBox()
        self.algo.addItems(["md5", "sha1", "sha256", "sha512", "crc32"])
        self.from_base = QComboBox()
        self.from_base.addItems(["10", "2", "8", "16"])
        self.to_base = QComboBox()
        self.to_base.addItems(["16", "2", "8", "10"])
        form.addRow("操作", self.op)
        form.addRow("算法/参数", self.algo)
        card.body.addLayout(form)
        root.addWidget(card)

        self.inp = QTextEdit()
        self.inp.setPlaceholderText("输入待处理内容…")
        root.addWidget(self.inp, 1)

        btn_row = QHBoxLayout()
        self.run_btn = PrimaryButton("处理")
        self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        out_card = Card()
        out_card.body.addWidget(SectionTitle("结果"))
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        out_card.body.addWidget(self.out, 1)
        root.addWidget(out_card, 1)
        # 初始化参数下拉可见性（currentTextChanged 已在构造期连接，但首次需手动触发）
        self._on_op()

    def _on_op(self) -> None:
        """根据所选操作显隐「算法/参数」相关的下拉框。"""
        op = self.op.currentText()
        self.algo.setVisible(op == "哈希")
        self.from_base.setVisible(op == "进制转换")
        self.to_base.setVisible(op == "进制转换")

    def _run(self) -> None:
        """按当前操作分派到 core/codec.py 对应函数，错误回显到结果框。"""
        op = self.op.currentText()
        text = self.inp.toPlainText()
        try:
            if op == "Base64 编码":
                res = codec.base64_encode(text)
            elif op == "Base64 解码":
                res = codec.base64_decode(text)
            elif op == "URL 编码":
                res = codec.url_encode(text)
            elif op == "URL 解码":
                res = codec.url_decode(text)
            elif op == "哈希":
                res = codec.hash_data(text, self.algo.currentText())
            elif op == "进制转换":
                res = codec.convert_base(text, int(self.from_base.currentText()),
                                         int(self.to_base.currentText()))
            elif op == "时间戳转换":
                res = codec.timestamp_convert(text)
            elif op == "JWT 解析":
                import json

                p = codec.jwt_parse(text)
                res = "Header:\n" + json.dumps(p.header, ensure_ascii=False, indent=2) + \
                      "\n\nPayload:\n" + json.dumps(p.payload, ensure_ascii=False, indent=2)
            elif op == "PEM 解析":
                p = codec.pem_parse(text)
                res = f"类型: {p.type}\n长度: {p.body_length}\n预览: {p.body_preview}"
            elif op == "文本→Hex":
                res = codec.to_hex(text)
            else:
                res = codec.from_hex(text)
            self.out.setPlainText(str(res))
        except Exception as exc:  # noqa: BLE001
            self.out.setPlainText(f"错误：{exc}")
