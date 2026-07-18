"""编解码工具模块（gui/codec_module.py）。对应 core/codec.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..core import codec


class CodecModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)

        form = QFormLayout()
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
        root.addLayout(form)

        self.inp = QTextEdit()
        self.inp.setPlaceholderText("输入待处理内容…")
        root.addWidget(self.inp)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("处理")
        self.run_btn.clicked.connect(self._run)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        root.addWidget(self.out)
        self._on_op()

    def _on_op(self) -> None:
        op = self.op.currentText()
        self.algo.setVisible(op == "哈希")
        self.from_base.setVisible(op == "进制转换")
        self.to_base.setVisible(op == "进制转换")

    def _run(self) -> None:
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
