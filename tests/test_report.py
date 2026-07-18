"""tests/test_report.py —— 报表自动化渲染与调度解析测试。"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from netops_studio.core import report as report_core  # noqa: E402


def _sample_data() -> dict:
    return {
        "generated_at": "2026-07-18T09:00:00",
        "sections": {
            "discovery": {
                "ok": True,
                "cidr": "192.168.1.0/24",
                "count": 2,
                "hosts": [
                    {"ip": "192.168.1.1", "hostname": "gw", "mac": "aa:bb:cc:00:00:01",
                     "vendor": "Huawei", "state": "up", "latency_ms": 1.2},
                    {"ip": "192.168.1.10", "hostname": "", "mac": "",
                     "vendor": "", "state": "up", "latency_ms": 3.4},
                ],
            },
            "speedtest": {
                "ok": True,
                "download_mbps": 95.5,
                "upload_mbps": 40.1,
                "latency_ms": 12.0,
                "loss_percent": 0.0,
                "success": True,
                "note": "",
            },
            "ipam": {
                "ok": False, "skipped": True, "error": "ipam 模块未提供（已跳过）",
            },
        },
    }


# --------------------------------------------------------------------------- #
# render_html
# --------------------------------------------------------------------------- #
def test_render_html_contains_title_and_sections():
    html = report_core.render_html(_sample_data())
    assert "NetOps Studio" in html
    assert "192.168.1.1" in html
    assert "gw" in html
    assert "<table" in html
    # 跳过的 section 也应在输出中体现
    assert "ipam" in html


def test_render_html_escapes_unsafe_content():
    data = {
        "generated_at": "t",
        "sections": {
            "discovery": {
                "ok": True, "cidr": "x", "count": 1,
                "hosts": [{"ip": "<script>", "hostname": "", "mac": "", "vendor": "",
                           "state": "up", "latency_ms": None}],
            }
        },
    }
    html = report_core.render_html(data)
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


# --------------------------------------------------------------------------- #
# render_markdown
# --------------------------------------------------------------------------- #
def test_render_markdown_contains_tables():
    md = report_core.render_markdown(_sample_data())
    assert "# NetOps Studio" in md
    assert "| IP | 主机名 | MAC | 厂商 | 状态 | 延迟(ms) |" in md
    assert "192.168.1.1" in md
    assert "95.5" in md
    # markdown 表格分隔行
    assert "---|" in md


def test_render_markdown_handles_skipped_section():
    md = report_core.render_markdown(_sample_data())
    assert "ipam 模块未提供" in md


# --------------------------------------------------------------------------- #
# parse_schedule
# --------------------------------------------------------------------------- #
def test_parse_schedule_daily():
    info = report_core.parse_schedule("0 9 * * *")
    assert info["minute"] == "0"
    assert info["hour"] == "9"
    assert info["summary"] == "每天 09:00"
    assert isinstance(info["next_run"], str) and ":" in info["next_run"]


def test_parse_schedule_every_minute():
    info = report_core.parse_schedule("* * * * *")
    assert info["summary"] == "每分钟"
    assert info["minute"] == "*"
    assert info["hour"] == "*"


def test_parse_schedule_hourly_minute():
    info = report_core.parse_schedule("30 * * * *")
    assert info["summary"] == "每小时第 30 分"


def test_parse_schedule_invalid_raises():
    with pytest.raises(ValueError):
        report_core.parse_schedule("bad spec")
    with pytest.raises(ValueError):
        report_core.parse_schedule("99 9 * * *")


# --------------------------------------------------------------------------- #
# InspectionJob
# --------------------------------------------------------------------------- #
def test_inspection_job_normalizes():
    job = report_core.InspectionJob(
        name="t", schedule="0 9 * * *",
        sections=["Discovery", "Speedtest"], export_format="PDF",
    )
    assert job.sections == ["discovery", "speedtest"]
    assert job.export_format == "pdf"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
