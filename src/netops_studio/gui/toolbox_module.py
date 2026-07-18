"""工具箱模块（gui/toolbox_module.py）。对应 core/toolbox.py。

用 QTabWidget 切换各小工具；每个工具为 输入 + 按钮 + 结果。纯计算同步执行，
无需 AsyncWorker。进制转换 / 时间戳转换 复用 core.codec。参考文档 §6.x。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from ..core import codec
from ..core.toolbox import (
    bandwidth, build_wol, gen_password, mask_to_wildcard, oui_lookup,
    unit_convert, wildcard_to_mask,
)


def _result_box() -> QTextEdit:
    box = QTextEdit()
    box.setReadOnly(True)
    box.setPlaceholderText("结果将在此显示…")
    return box


class ToolboxModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)

        tabs = QTabWidget()
        root.addWidget(tabs)

        tabs.addTab(self._mask_tab(), "掩码/通配符")
        tabs.addTab(self._oui_tab(), "OUI 查询")
        tabs.addTab(self._pwd_tab(), "密码生成")
        tabs.addTab(self._bw_tab(), "带宽计算")
        tabs.addTab(self._unit_tab(), "单位换算")
        tabs.addTab(self._wol_tab(), "WOL 魔术包")
        tabs.addTab(self._base_tab(), "进制转换")
        tabs.addTab(self._ts_tab(), "时间戳转换")

    # ------------------------------------------------------------------ 掩码
    def _mask_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        mask = QLineEdit("255.255.255.0")
        wc = QLineEdit("0.0.0.255")
        form.addRow("子网掩码", mask)
        form.addRow("通配符", wc)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        b1 = QPushButton("掩码 → 通配符")
        b1.clicked.connect(lambda: self._safe(out, lambda: mask_to_wildcard(mask.text())))
        b2 = QPushButton("通配符 → 掩码")
        b2.clicked.connect(lambda: self._safe(out, lambda: wildcard_to_mask(wc.text())))
        btn_row.addWidget(b1)
        btn_row.addWidget(b2)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    # ------------------------------------------------------------------ OUI
    def _oui_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        mac = QLineEdit("00:0C:29:AB:CD:EF")
        form.addRow("MAC 地址", mac)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        b = QPushButton("查询厂商")
        b.clicked.connect(lambda: self._safe(out, lambda: oui_lookup(mac.text()) or "（未知厂商）"))
        btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    # ---------------------------------------------------------------- 密码
    def _pwd_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        length = QLineEdit("16")
        form.addRow("长度", length)
        layout.addLayout(form)

        opt_row = QHBoxLayout()
        c_upper = QCheckBox("大写"); c_upper.setChecked(True)
        c_lower = QCheckBox("小写"); c_lower.setChecked(True)
        c_digit = QCheckBox("数字"); c_digit.setChecked(True)
        c_symbol = QCheckBox("符号"); c_symbol.setChecked(True)
        for c in (c_upper, c_lower, c_digit, c_symbol):
            opt_row.addWidget(c)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        btn_row = QHBoxLayout()
        b = QPushButton("生成密码")
        b.clicked.connect(
            lambda: self._safe(
                out,
                lambda: gen_password(
                    int(length.text() or "16"),
                    upper=c_upper.isChecked(), lower=c_lower.isChecked(),
                    digit=c_digit.isChecked(), symbol=c_symbol.isChecked(),
                ),
            )
        )
        btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    # ---------------------------------------------------------------- 带宽
    def _bw_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        size = QLineEdit("1000000")
        secs = QLineEdit("1")
        ovh = QLineEdit("1.0")
        form.addRow("字节数 (size_bytes)", size)
        form.addRow("耗时 (seconds)", secs)
        form.addRow("开销系数 (overhead)", ovh)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        b = QPushButton("计算带宽")
        b.clicked.connect(
            lambda: self._safe(
                out,
                lambda: f"{bandwidth(float(size.text()), float(secs.text()), float(ovh.text())):.4f} Mbps",
            )
        )
        btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    # ---------------------------------------------------------------- 单位
    def _unit_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        value = QLineEdit("1")
        from_u = QComboBox()
        from_u.addItems(["B", "KB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB",
                         "bps", "kbps", "Mbps", "Gbps"])
        to_u = QComboBox()
        to_u.addItems(["B", "KB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB",
                       "bps", "kbps", "Mbps", "Gbps"])
        to_u.setCurrentText("B")
        form.addRow("数值", value)
        form.addRow("从单位", from_u)
        form.addRow("到单位", to_u)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        b = QPushButton("换算")
        b.clicked.connect(
            lambda: self._safe(
                out,
                lambda: str(unit_convert(float(value.text()), from_u.currentText(),
                                         to_u.currentText())),
            )
        )
        btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    # ---------------------------------------------------------------- WOL
    def _wol_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        mac = QLineEdit("00:11:22:33:44:55")
        form.addRow("目标 MAC", mac)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        b = QPushButton("构造魔术包")
        b.clicked.connect(
            lambda: self._safe(
                out,
                lambda: self._wol_preview(build_wol(mac.text())),
            )
        )
        btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    @staticmethod
    def _wol_preview(pkt: bytes) -> str:
        hexed = pkt.hex(" ").upper()
        return f"长度: {len(pkt)} 字节\n{hexed}"

    # ---------------------------------------------------------------- 进制
    def _base_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        value = QLineEdit("255")
        from_b = QComboBox()
        from_b.addItems(["10", "2", "8", "16"])
        from_b.setCurrentText("10")
        to_b = QComboBox()
        to_b.addItems(["16", "2", "8", "10"])
        to_b.setCurrentText("16")
        form.addRow("数值", value)
        form.addRow("源进制", from_b)
        form.addRow("目标进制", to_b)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        b = QPushButton("转换")
        b.clicked.connect(
            lambda: self._safe(
                out,
                lambda: codec.convert_base(value.text(), int(from_b.currentText()),
                                           int(to_b.currentText())),
            )
        )
        btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    # -------------------------------------------------------------- 时间戳
    def _ts_tab(self) -> QWidget:
        w = QWidget()
        out = _result_box()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        value = QLineEdit("now")
        to = QComboBox()
        to.addItems(["human", "ts"])
        form.addRow("值 (时间戳/now/时间串)", value)
        form.addRow("目标", to)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        b = QPushButton("转换")
        b.clicked.connect(
            lambda: self._safe(
                out,
                lambda: codec.timestamp_convert(value.text(), to.currentText()),
            )
        )
        btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        layout.addWidget(out)
        return w

    # -------------------------------------------------------------- 工具
    @staticmethod
    def _safe(out: QTextEdit, fn) -> None:
        try:
            out.setPlainText(str(fn()))
        except Exception as exc:  # noqa: BLE001
            out.setPlainText(f"错误：{exc}")
