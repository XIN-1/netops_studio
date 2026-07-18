"""性能与测速模块（gui/speed_test_module.py）。对应 core/speedtest.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QLabel, QLineEdit, QTextEdit, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker, bus
from ..app.async_worker import JobBase
from ..core.speedtest import ExternalTester, Iperf3Client, find_iperf3
from .widgets import Card, PrimaryButton, SectionTitle


class ExternalJob(JobBase):
    def __init__(self, download_secs: int = 8) -> None:
        super().__init__()
        self.download_secs = download_secs

    def run_job(self) -> None:
        tester = ExternalTester()
        res = tester.measure(download_secs=self.download_secs)
        self.signals.result.emit(res)


class SpeedTestModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)

        head = QVBoxLayout()
        head.setSpacing(2)
        t = QLabel("性能与测速")
        t.setProperty("role", "title")
        s = QLabel("外网探测 + iperf3 内网吞吐")
        s.setProperty("role", "subtitle")
        head.addWidget(t)
        head.addWidget(s)
        root.addLayout(head)

        # 外网测速
        ext = Card()
        ext.body.addWidget(SectionTitle("外网测速（HTTP 探针）"))
        self.ext_btn = PrimaryButton("开始测速")
        self.ext_btn.clicked.connect(self._external)
        ext.body.addWidget(self.ext_btn)
        self.ext_out = QLabel("下行 / 上行 / 延迟：—")
        self.ext_out.setProperty("role", "muted")
        ext.body.addWidget(self.ext_out)
        root.addWidget(ext)

        # iperf3 内网
        iperf = Card()
        iperf.body.addWidget(SectionTitle("iperf3 内网测速"))
        il = QFormLayout()
        il.setContentsMargins(0, 0, 0, 0)
        self.server = QLineEdit("127.0.0.1")
        self.port = QLineEdit("5201")
        self.dur = QLineEdit("10")
        il.addRow("服务端 IP", self.server)
        il.addRow("端口", self.port)
        il.addRow("时长(秒)", self.dur)
        iperf.body.addLayout(il)
        btn = PrimaryButton("运行 iperf3 客户端")
        btn.clicked.connect(self._iperf)
        iperf.body.addWidget(btn)
        root.addWidget(iperf)

        console_card = Card()
        console_card.body.addWidget(SectionTitle("控制台"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        console_card.body.addWidget(self.console, 1)
        root.addWidget(console_card, 1)

        self._log(f"iperf3 内置二进制：{find_iperf3() or '未找到（将使用系统 PATH 或提示安装）'}")

    def _log(self, msg: str) -> None:
        self.console.append(msg)

    def _external(self) -> None:
        self.ext_btn.setEnabled(False)
        job = ExternalJob(download_secs=8)
        self.worker.submit(job, on_result=self._on_ext, on_finished=lambda: self.ext_btn.setEnabled(True))

    def _on_ext(self, res) -> None:
        self.ext_out.setText(
            f"下行 {res.download_mbps} Mbps | 上行 {res.upload_mbps} Mbps | "
            f"延迟 {res.latency_ms} ms | 丢包 {res.loss_percent}%"
        )
        self._log(f"外网测速：{res.download_mbps} Mbps 下行，延迟 {res.latency_ms} ms")
        bus.publish("speedtest.result", res)

    def _iperf(self) -> None:
        try:
            client = Iperf3Client()
            if not client.available:
                self._log("未找到 iperf3，请安装 iperf3 或放入 resources/bin/<os>/")
                return
            res = client.run(self.server.text(), int(self.port.text()), duration=int(self.dur.text()))
            self._log(f"iperf3 结果：{res.direction} {res.bandwidth_mbps} Mbps")
            bus.publish("speedtest.result", res)
        except Exception as exc:  # noqa: BLE001
            self._log(f"iperf3 失败：{exc}")
