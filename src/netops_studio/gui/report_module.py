"""报表自动化模块（gui/report_module.py）。对应 core/report.py。"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker, bus
from ..app.async_worker import JobBase
from ..core import report as report_core
from ..core.report import InspectionJob

_FORMAT_LABELS = {
    "html": "HTML",
    "pdf": "PDF",
    "docx": "Word",
    "xlsx": "Excel",
}
_SECTION_LABELS = {
    "discovery": "网络发现 (discovery)",
    "speedtest": "性能测速 (speedtest)",
    "ipam": "IP 地址管理 (ipam)",
    "security": "安全管理 (security)",
}


class ReportJob(JobBase):
    """后台聚合巡检数据（协作式取消）。"""

    def __init__(self, sections: list, opts: Optional[dict] = None) -> None:
        super().__init__()
        self.sections = sections
        self.opts = opts or {}

    def run_job(self) -> None:
        data = report_core.gather(self.sections, **self.opts)
        self.signals.result.emit(data)


class ReportModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        self._report_data: Optional[Dict[str, Any]] = None
        self._rendered_html: str = ""
        self._rendered_md: str = ""

        root = QVBoxLayout(self)

        # 调度与 section 选择
        cfg = QGroupBox("巡检配置")
        cl = QVBoxLayout(cfg)

        self.sched_edit = QLineEdit("0 9 * * *")
        self.sched_edit.setToolTip("cron-like：分 时 日 月 周，如 '0 9 * * *' 每天 09:00")
        self.sched_hint = QLabel("下次运行：—")
        sched_row = QHBoxLayout()
        sched_row.addWidget(QLabel("调度"))
        sched_row.addWidget(self.sched_edit, 1)
        sched_row.addWidget(self.sched_hint)
        cl.addLayout(sched_row)

        self.section_boxes: Dict[str, QCheckBox] = {}
        sec_row = QHBoxLayout()
        for sec in report_core.VALID_SECTIONS:
            cb = QCheckBox(_SECTION_LABELS.get(sec, sec))
            cb.setChecked(sec in ("discovery", "speedtest"))
            self.section_boxes[sec] = cb
            sec_row.addWidget(cb)
        sec_row.addStretch()
        cl.addLayout(sec_row)

        root.addWidget(cfg)

        # 格式与操作
        op = QHBoxLayout()
        self.fmt = QComboBox()
        for key, label in _FORMAT_LABELS.items():
            self.fmt.addItem(label, key)
        self.fmt.setCurrentIndex(0)
        op.addWidget(QLabel("导出格式"))
        op.addWidget(self.fmt)

        self.gen_btn = QPushButton("生成")
        self.gen_btn.clicked.connect(self._generate)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self.worker.cancel)
        self.export_btn = QPushButton("导出文件")
        self.export_btn.clicked.connect(self._export)

        op.addStretch()
        op.addWidget(self.gen_btn)
        op.addWidget(self.stop_btn)
        op.addWidget(self.export_btn)
        root.addLayout(op)

        self.status = QLabel("就绪")
        root.addWidget(self.status)

        # 预览
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setAcceptRichText(False)
        root.addWidget(self.preview, 1)

        # 初始化调度提示
        self._refresh_schedule()

    # ------------------------------------------------------------------ #
    def _selected_sections(self) -> list:
        return [s for s, cb in self.section_boxes.items() if cb.isChecked()]

    def _refresh_schedule(self) -> None:
        try:
            info = report_core.parse_schedule(self.sched_edit.text())
            self.sched_hint.setText(f"下次运行：{info['next_run']}（{info['summary']}）")
        except Exception as exc:  # noqa: BLE001
            self.sched_hint.setText(f"调度解析失败：{exc}")

    def _generate(self) -> None:
        sections = self._selected_sections()
        if not sections:
            self.status.setText("请至少勾选一个 section")
            return
        try:
            report_core.parse_schedule(self.sched_edit.text())
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"调度表达式非法：{exc}")
            return

        self.preview.clear()
        self.status.setText("生成中…")
        job = ReportJob(sections, opts={"cidr": "192.168.1.0/24"})
        self.worker.submit(job, on_result=self._on_result, on_error=self._on_error)

    def _on_result(self, data: Dict[str, Any]) -> None:
        self._report_data = data
        self._rendered_html = report_core.render_html(data)
        self._rendered_md = report_core.render_markdown(data)

        fmt = self.fmt.currentData()
        self.preview.setPlainText(
            self._rendered_html if fmt in ("html", "pdf") else self._rendered_md
        )
        self.status.setText("生成完成，可在右侧选择格式预览或导出")

        # 经事件总线通知仪表盘
        bus.publish("report.generated", data)

    def _on_error(self, msg: str) -> None:
        self.status.setText(f"生成失败：{msg}")

    def _export(self) -> None:
        if not self._report_data:
            self.status.setText("请先生成报告")
            return
        fmt = self.fmt.currentData()
        ext = {"html": "html", "pdf": "pdf", "docx": "docx", "xlsx": "xlsx"}[fmt]
        path, _ = QFileDialog.getSaveFileName(self, "导出报告", f"report.{ext}", f"*.{ext}")
        if not path:
            return
        try:
            if fmt == "html":
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._rendered_html)
            elif fmt == "pdf":
                report_core.export_pdf(self._rendered_html, path)
            elif fmt == "docx":
                report_core.export_docx(self._report_data, path)
            elif fmt == "xlsx":
                report_core.export_excel(self._report_data, path)
            self.status.setText(f"已导出：{os.path.basename(path)}")
        except Exception as exc:  # noqa: BLE001
            self.status.setText(f"导出失败：{exc}")
