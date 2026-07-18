"""音视频物联模块（gui/aviot_module.py）。对应 core/av_iot.py。

提供 ONVIF 发现、RTSP 流探测、SIP/VoIP 语音质量评估三类操作，
结果经 AsyncWorker + JobBase 在后台线程执行，主线程渲染。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import av_iot


class AvIotJob(JobBase):
    """后台执行音视频物联任务（协作式取消）。"""

    def __init__(self, op: str, **params) -> None:
        super().__init__()
        self.op = op
        self.params = params

    def run_job(self) -> None:
        if self.op == "ONVIF发现":
            devices = av_iot.discover_onvif(timeout=self.params.get("timeout", 3.0))
            self.signals.result.emit(devices)
        elif self.op == "流探测":
            result = av_iot.describe_stream(
                self.params.get("url", ""),
                timeout=self.params.get("timeout", 5),
                user=self.params.get("user", ""),
                pwd=self.params.get("pwd", ""),
            )
            self.signals.result.emit(result)
        elif self.op == "语音质量评估":
            mos = av_iot.estimate_mos(
                self.params.get("loss_percent", 0.0),
                self.params.get("jitter_ms", 0.0),
            )
            self.signals.result.emit(mos)
        else:
            raise ValueError(f"未知操作：{self.op}")


class AvIotModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)

        # ---- ONVIF 发现 ----
        onvif = QGroupBox("ONVIF 发现（WS-Discovery 多播）")
        ol = QFormLayout(onvif)
        self.onvif_timeout = QLineEdit("3")
        ol.addRow("超时(秒)", self.onvif_timeout)
        self.onvif_btn = QPushButton("ONVIF 发现")
        self.onvif_btn.clicked.connect(self._onvif)
        ol.addRow(self.onvif_btn)
        root.addWidget(onvif)

        # ---- RTSP 流探测 ----
        stream = QGroupBox("RTSP 流探测")
        sl = QFormLayout(stream)
        self.rtsp_url = QLineEdit("rtsp://192.168.1.64:554/stream1")
        sl.addRow("RTSP URL", self.rtsp_url)
        self.stream_user = QLineEdit("")
        self.stream_user.setPlaceholderText("可选")
        self.stream_pwd = QLineEdit("")
        self.stream_pwd.setPlaceholderText("可选")
        sl.addRow("用户名", self.stream_user)
        sl.addRow("密码", self.stream_pwd)
        self.stream_btn = QPushButton("流探测")
        self.stream_btn.clicked.connect(self._stream)
        sl.addRow(self.stream_btn)
        root.addWidget(stream)

        # ---- SIP / VoIP 质量 ----
        voip = QGroupBox("SIP / VoIP 语音质量（E-model）")
        vl = QFormLayout(voip)
        self.loss = QLineEdit("0")
        self.jitter = QLineEdit("0")
        vl.addRow("丢包率(%)", self.loss)
        vl.addRow("抖动(ms)", self.jitter)
        self.mos_btn = QPushButton("语音质量评估")
        self.mos_btn.clicked.connect(self._mos)
        vl.addRow(self.mos_btn)
        root.addWidget(voip)

        # ---- 停止 ----
        btn_row = QHBoxLayout()
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.worker.cancel)
        self.progress = QLabel("就绪")
        btn_row.addWidget(self.stop_btn)
        btn_row.addWidget(self.progress)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # ---- 结果 ----
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段", "值", "", ""])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)

        self.raw = QTextEdit()
        self.raw.setReadOnly(True)
        root.addWidget(self.raw)

    # ----- 触发 ----
    def _onvif(self) -> None:
        self.raw.clear()
        self.progress.setText("ONVIF 发现中…")
        job = AvIotJob("ONVIF发现", timeout=float(self.onvif_timeout.text() or 3))
        self.worker.submit(job, on_result=self._show_onvif,
                           on_error=self._err, on_finished=self._done)

    def _stream(self) -> None:
        self.raw.clear()
        self.progress.setText("RTSP 流探测中…")
        job = AvIotJob(
            "流探测",
            url=self.rtsp_url.text().strip(),
            timeout=5,
            user=self.stream_user.text().strip(),
            pwd=self.stream_pwd.text().strip(),
        )
        self.worker.submit(job, on_result=self._show_stream,
                           on_error=self._err, on_finished=self._done)

    def _mos(self) -> None:
        self.raw.clear()
        try:
            loss = float(self.loss.text() or 0)
            jitter = float(self.jitter.text() or 0)
        except ValueError:
            self.progress.setText("输入无效：丢包率/抖动须为数字")
            return
        self.progress.setText("评估中…")
        job = AvIotJob("语音质量评估", loss_percent=loss, jitter_ms=jitter)
        self.worker.submit(job, on_result=self._show_mos,
                           on_error=self._err, on_finished=self._done)

    # ----- 渲染 ----
    def _show_onvif(self, devices) -> None:
        self.raw.setPlainText(f"发现 {len(devices)} 台设备")
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["端点", "类型", "XAddrs", "Scopes"])
        self.table.setRowCount(len(devices))
        for i, d in enumerate(devices):
            self.table.setItem(i, 0, QTableWidgetItem(d.endpoint))
            self.table.setItem(i, 1, QTableWidgetItem(d.types))
            self.table.setItem(i, 2, QTableWidgetItem(" ".join(d.xaddrs)))
            self.table.setItem(i, 3, QTableWidgetItem(" ".join(d.scopes)))

    def _show_stream(self, result) -> None:
        self.raw.setPlainText(result.get("sdp", ""))
        tracks = result.get("tracks", [])
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["媒体", "编解码", "时钟(Hz)", "控制"])
        self.table.setRowCount(len(tracks))
        for i, t in enumerate(tracks):
            self.table.setItem(i, 0, QTableWidgetItem(t.media))
            self.table.setItem(i, 1, QTableWidgetItem(t.codec))
            self.table.setItem(i, 2, QTableWidgetItem(str(t.clock_rate)))
            self.table.setItem(i, 3, QTableWidgetItem(t.control))

    def _show_mos(self, mos) -> None:
        rating = (
            "优" if mos >= 4.0 else
            "良" if mos >= 3.5 else
            "中" if mos >= 3.0 else
            "差" if mos >= 2.0 else "不可接受"
        )
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["指标", "值"])
        self.table.setRowCount(2)
        self.table.setItem(0, 0, QTableWidgetItem("估算 MOS"))
        self.table.setItem(0, 1, QTableWidgetItem(f"{mos:.2f}"))
        self.table.setItem(1, 0, QTableWidgetItem("语音质量"))
        self.table.setItem(1, 1, QTableWidgetItem(rating))
        self.raw.setPlainText(f"MOS = {mos:.2f}（{rating}）")

    def _err(self, msg: str) -> None:
        self.progress.setText("出错")
        self.raw.setPlainText(msg)

    def _done(self) -> None:
        if self.progress.text().endswith("…"):
            self.progress.setText("完成")
