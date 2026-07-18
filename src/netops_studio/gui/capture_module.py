"""抓包分析模块（gui/capture_module.py）。对应 core/capture.py。

选择网卡/时长 抓包，或分析已有 pcap；表格展示 协议分布 / 会话 TopN / 异常。
耗时操作走 AsyncWorker + JobBase，主线程仅渲染。
"""

from __future__ import annotations

import os
import tempfile
import time

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import capture as capcore


class CaptureJob(JobBase):
    """后台抓包并对落盘 pcap 做聚合分析。"""

    def __init__(self, interface: str, duration: int, outfile: str) -> None:
        super().__init__()
        self.interface = interface
        self.duration = duration
        self.outfile = outfile

    def run_job(self) -> None:
        capcore.capture(self.interface, self.duration, self.outfile)
        result = capcore.analyze_pcap(self.outfile)
        result["captured"] = self.outfile
        self.signals.result.emit(result)


class AnalyzeJob(JobBase):
    """后台分析已有 pcap。"""

    def __init__(self, pcap: str) -> None:
        super().__init__()
        self.pcap = pcap

    def run_job(self) -> None:
        result = capcore.analyze_pcap(self.pcap)
        result["analyzed"] = self.pcap
        self.signals.result.emit(result)


class CaptureModule(QWidget):
    """抓包分析模块（对应 core/capture.py）。

    支持选择网卡抓包到临时/指定 pcap，或分析已有 pcap；耗时操作（capture /
    analyze_pcap）均经 AsyncWorker 后台执行。结果以三个 Tab 渲染：协议字节分布、
    会话 TopN、异常列表。网卡列表依赖 tshark，缺失时给出友好提示。
    """

    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        root = QVBoxLayout(self)

        form = QFormLayout()
        self.iface = QComboBox()
        self.iface.setMinimumWidth(200)
        self.duration = QSpinBox()
        self.duration.setRange(1, 3600)
        self.duration.setValue(10)
        form.addRow("网卡", self.iface)
        form.addRow("时长(秒)", self.duration)
        root.addLayout(form)

        file_row = QHBoxLayout()
        self.file_edit = QLineEdit("")
        self.file_edit.setPlaceholderText("分析已有 pcap（留空则抓包到临时文件）")
        browse = QPushButton("浏览...")
        browse.clicked.connect(self._browse)
        file_row.addWidget(QLabel("pcap"))
        file_row.addWidget(self.file_edit, 1)
        file_row.addWidget(browse)
        root.addLayout(file_row)

        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新网卡")
        self.refresh_btn.clicked.connect(self._refresh_ifaces)
        self.capture_btn = QPushButton("开始抓包")
        self.capture_btn.clicked.connect(self._capture)
        self.analyze_btn = QPushButton("分析已有pcap")
        self.analyze_btn.clicked.connect(self._analyze)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.worker.cancel)
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.capture_btn)
        btn_row.addWidget(self.analyze_btn)
        btn_row.addWidget(self.stop_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.status = QLabel("就绪")
        root.addWidget(self.status)

        tabs = QTabWidget()
        self.proto_table = QTableWidget(0, 2)
        self.proto_table.setHorizontalHeaderLabels(["协议", "字节数"])
        self.proto_table.horizontalHeader().setStretchLastSection(True)
        self.conv_table = QTableWidget(0, 4)
        self.conv_table.setHorizontalHeaderLabels(["源", "目的", "包数", "字节数"])
        self.conv_table.horizontalHeader().setStretchLastSection(True)
        self.anom_table = QTableWidget(0, 4)
        self.anom_table.setHorizontalHeaderLabels(["类型", "严重度", "描述", "详情"])
        self.anom_table.horizontalHeader().setStretchLastSection(True)
        tabs.addTab(self.proto_table, "协议分布")
        tabs.addTab(self.conv_table, "会话 TopN")
        tabs.addTab(self.anom_table, "异常")
        root.addWidget(tabs, 1)

    # ---------------------------------------------------------------- 交互
    def _browse(self) -> None:
        """打开文件选择对话框，选定要分析的 pcap 路径。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 pcap", "", "pcap (*.pcap *.pcapng);;All (*)"
        )
        if path:
            self.file_edit.setText(path)

    def _refresh_ifaces(self) -> None:
        """调用 capcore.list_interfaces 刷新网卡下拉；tshark 缺失时友好提示。"""
        self.iface.clear()
        try:
            ifaces = capcore.list_interfaces()
        except capcore.TsharkNotFoundError as exc:
            self.status.setText(f"错误：{exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"列举网卡失败：{exc}")
            return
        for i in ifaces:
            label = i["name"] + (f" ({i['description']})" if i["description"] else "")
            self.iface.addItem(label, i["name"])
        self.status.setText(f"已发现 {len(ifaces)} 个网卡" if ifaces else "未发现网卡")

    def _capture(self) -> None:
        """校验网卡后提交抓包任务；未指定输出文件则落到临时目录。"""
        iface = self.iface.currentData() or self.iface.currentText()
        if not iface:
            self.status.setText("请先选择网卡（点击『刷新网卡』）")
            return
        outfile = self.file_edit.text().strip() or os.path.join(
            tempfile.gettempdir(), f"capture_{int(time.time())}.pcap"
        )
        self.file_edit.setText(outfile)
        self.status.setText(f"抓包中：{iface} {self.duration.value()}s ...")
        job = CaptureJob(iface, self.duration.value(), outfile)
        self.worker.submit(job, on_result=self._show, on_error=self._err)

    def _analyze(self) -> None:
        """校验 pcap 文件存在后提交分析任务。"""
        pcap = self.file_edit.text().strip()
        if not pcap or not os.path.isfile(pcap):
            self.status.setText("请选择有效的 pcap 文件")
            return
        self.status.setText(f"分析中：{pcap}")
        job = AnalyzeJob(pcap)
        self.worker.submit(job, on_result=self._show, on_error=self._err)

    def _err(self, msg: str) -> None:
        """错误回调：在状态标签展示后台任务异常。"""
        self.status.setText(f"错误：{msg}")

    # ---------------------------------------------------------------- 渲染
    def _show(self, result: dict) -> None:
        """结果回调：渲染协议分布 / 会话 TopN（按字节取前 100）/ 异常三表。"""
        self.status.setText("完成")

        protos = result.get("protocols", {})
        self.proto_table.setRowCount(len(protos))
        for i, (k, v) in enumerate(sorted(protos.items(), key=lambda x: -x[1])):
            self.proto_table.setItem(i, 0, QTableWidgetItem(k))
            self.proto_table.setItem(i, 1, QTableWidgetItem(str(v)))

        convs = result.get("conversations", [])
        top = sorted(convs, key=lambda c: c.get("bytes", 0), reverse=True)[:100]
        self.conv_table.setRowCount(len(top))
        for i, c in enumerate(top):
            self.conv_table.setItem(i, 0, QTableWidgetItem(str(c.get("src", ""))))
            self.conv_table.setItem(i, 1, QTableWidgetItem(str(c.get("dst", ""))))
            self.conv_table.setItem(i, 2, QTableWidgetItem(str(c.get("packets", 0))))
            self.conv_table.setItem(i, 3, QTableWidgetItem(str(c.get("bytes", 0))))

        anoms = result.get("anomalies", [])
        self.anom_table.setRowCount(len(anoms))
        for i, a in enumerate(anoms):
            self.anom_table.setItem(i, 0, QTableWidgetItem(str(a.get("type", ""))))
            self.anom_table.setItem(i, 1, QTableWidgetItem(str(a.get("severity", ""))))
            self.anom_table.setItem(i, 2, QTableWidgetItem(str(a.get("message", ""))))
            self.anom_table.setItem(i, 3, QTableWidgetItem(str(a.get("detail", ""))))
