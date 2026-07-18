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
    """外网测速任务（对应 core/speedtest.ExternalTester）。

    在后台线程跑 HTTP 探针，结果经 ``signals.result`` 上报。
    """

    def __init__(self, download_secs: int = 8) -> None:
        super().__init__()
        self.download_secs = download_secs

    def run_job(self) -> None:
        tester = ExternalTester()
        res = tester.measure(download_secs=self.download_secs)
        self.signals.result.emit(res)


class IperfJob(JobBase):
    """iperf3 内网吞吐任务（对应 core/speedtest.Iperf3Client）。

    在后台线程跑 iperf3 客户端（大流量/长时长测试可能耗时数秒到数十秒），
    避免阻塞 GUI 主线程导致界面卡顿；结果经 ``signals.result`` 上报。
    """

    def __init__(self, server: str, port: int, duration: int) -> None:
        super().__init__()
        self.server = server
        self.port = port
        self.duration = duration

    def run_job(self) -> None:
        client = Iperf3Client()
        if not client.available:
            # 以异常形式上抛，由 AsyncWorker 转成 error 信号统一处理（不阻塞线程）。
            raise RuntimeError("未找到 iperf3，请安装 iperf3 或放入 resources/bin/<os>/")
        res = client.run(self.server, self.port, duration=self.duration)
        self.signals.result.emit(res)


class SpeedTestModule(QWidget):
    """性能与测速模块（对应 core/speedtest.py）。

    提供两块能力：外网 HTTP 探针（经 AsyncWorker 后台执行，期间禁用按钮）
    与 iperf3 内网吞吐（需服务端）。两次测速结果均 publish ``speedtest.result``
    事件供仪表盘聚合。
    """

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
        self.iperf_btn = PrimaryButton("运行 iperf3 客户端")
        self.iperf_btn.clicked.connect(self._iperf)
        iperf.body.addWidget(self.iperf_btn)
        root.addWidget(iperf)

        console_card = Card()
        console_card.body.addWidget(SectionTitle("控制台"))
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        console_card.body.addWidget(self.console, 1)
        root.addWidget(console_card, 1)

        self._log(f"iperf3 内置二进制：{find_iperf3() or '未找到（将使用系统 PATH 或提示安装）'}")

    def _log(self, msg: str) -> None:
        """向只读控制台追加一行日志。"""
        self.console.append(msg)

    def _external(self) -> None:
        """触发外网测速：禁用按钮避免重复点击，完成后恢复。"""
        self.ext_btn.setEnabled(False)
        job = ExternalJob(download_secs=8)
        self.worker.submit(job, on_result=self._on_ext, on_finished=lambda: self.ext_btn.setEnabled(True))

    def _on_ext(self, res) -> None:
        """外网测速结果回调：刷新读数并广播 ``speedtest.result``。"""
        self.ext_out.setText(
            f"下行 {res.download_mbps} Mbps | 上行 {res.upload_mbps} Mbps | "
            f"延迟 {res.latency_ms} ms | 丢包 {res.loss_percent}%"
        )
        self._log(f"外网测速：{res.download_mbps} Mbps 下行，延迟 {res.latency_ms} ms")
        bus.publish("speedtest.result", res)

    def _iperf(self) -> None:
        """运行 iperf3 客户端（经 AsyncWorker 后台执行，避免阻塞 GUI 线程）。

        提交前禁用按钮，完成后复位；结果回调里刷新日志并广播
        ``speedtest.result`` 事件供仪表盘聚合。
        """
        try:
            port = int(self.port.text())
            duration = int(self.dur.text())
        except ValueError:
            self._log("端口 / 时长必须为整数")
            return
        self.iperf_btn.setEnabled(False)
        self._log(f"iperf3 客户端启动：{self.server.text()}:{port}，时长 {duration}s …")
        job = IperfJob(self.server.text(), port, duration)
        self.worker.submit(
            job,
            on_result=self._on_iperf,
            on_error=self._on_iperf_error,
            on_finished=lambda: self.iperf_btn.setEnabled(True),
        )

    def _on_iperf(self, res) -> None:
        """iperf3 结果回调：刷新日志并广播 ``speedtest.result``。"""
        self._log(f"iperf3 结果：{res.direction} {res.bandwidth_mbps} Mbps")
        bus.publish("speedtest.result", res)

    def _on_iperf_error(self, msg: str) -> None:
        """iperf3 错误回调：在控制台回显异常文本。"""
        self._log(f"iperf3 失败：{msg}")
