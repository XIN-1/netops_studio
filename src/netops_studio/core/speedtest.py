"""性能与测速引擎（core/speedtest.py）。

参考开发文档 §6.4。封装 iperf3（随包二进制），并内置自建 HTTP 探针做外网测速兜底。
iperf3 二进制按平台从 resources/bin/<os>/ 加载。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

_SYSTEM = platform.system().lower()

_RESOURCE_BIN = {
    "windows": ("iperf3.exe", "resources/bin/windows/iperf3.exe"),
    "linux": ("iperf3", "resources/bin/linux/iperf3"),
    "darwin": ("iperf3", "resources/bin/macos/iperf3"),
}


@dataclass
class SpeedResult:
    direction: str  # download / upload
    bandwidth_mbps: float
    jitter_ms: Optional[float] = None
    loss_percent: Optional[float] = None
    raw: str = ""
    success: bool = False


@dataclass
class ExternalSpeed:
    download_mbps: float = 0.0
    upload_mbps: float = 0.0
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    loss_percent: float = 0.0
    success: bool = False
    note: str = ""


def find_iperf3(pkg_root: Optional[str] = None) -> Optional[str]:
    """查找 iperf3 可执行文件：优先 resources 自带，其次系统 PATH。"""
    if pkg_root:
        _, rel = _RESOURCE_BIN.get(_SYSTEM, ("iperf3", ""))
        if rel:
            bundled = os.path.join(pkg_root, rel)
            if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
                return bundled
    return shutil.which("iperf3")


class Iperf3Server:
    """iperf3 服务端封装（TCP/UDP）。"""

    def __init__(self, pkg_root: Optional[str] = None):
        self.bin = find_iperf3(pkg_root)
        self.proc: Optional[subprocess.Popen] = None

    @property
    def available(self) -> bool:
        return self.bin is not None

    def start(self, port: int = 5201, udp: bool = False) -> None:
        if not self.bin:
            raise RuntimeError("未找到 iperf3 二进制，请先安装或放入 resources/bin")
        cmd = [self.bin, "-s", "-p", str(port)] + (["-u"] if udp else [])
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


class Iperf3Client:
    """iperf3 客户端封装（TCP/UDP，双向）。"""

    def __init__(self, pkg_root: Optional[str] = None):
        self.bin = find_iperf3(pkg_root)

    @property
    def available(self) -> bool:
        return self.bin is not None

    def run(self, server: str, port: int = 5201, udp: bool = False,
            duration: int = 10, reverse: bool = False) -> SpeedResult:
        if not self.bin:
            raise RuntimeError("未找到 iperf3 二进制，请先安装或放入 resources/bin")
        cmd = [self.bin, "-c", server, "-p", str(port), "-t", str(duration), "-J",
               "-f", "m"]
        if udp:
            cmd += ["-u", "-b", "100M"]
        if reverse:
            cmd += ["-R"]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
        return self._parse(out.stdout, "upload" if reverse else "download")

    @staticmethod
    def _parse(stdout: str, direction: str) -> SpeedResult:
        """解析 iperf3 的 -J JSON 输出为 SpeedResult。

        download 取 sum_received、upload 取 sum_sent 的 bits_per_second；
        UDP 额外取 sum 中的抖动与丢包率。解析失败返回 success=False 的占位结果。
        """
        import json

        try:
            data = json.loads(stdout)
            end = data.get("end", {})
            if direction == "download":
                bps = end.get("sum_received", {}).get("bits_per_second", 0)
            else:
                bps = end.get("sum_sent", {}).get("bits_per_second", 0)
            udp = end.get("sum", {})
            return SpeedResult(
                direction=direction,
                bandwidth_mbps=round(bps / 1_000_000, 2),
                jitter_ms=(float(udp.get("jitter_ms", 0)) if udp else None),
                loss_percent=(float(udp.get("lost_percent", 0)) if udp else None),
                raw=stdout[:500],
                success=True,
            )
        except (json.JSONDecodeError, KeyError):
            return SpeedResult(direction=direction, bandwidth_mbps=0.0, success=False, raw=stdout[:500])


class ExternalTester:
    """外网测速：自建 HTTP 探针，下载/上行测速 + 延迟（无第三方依赖）。"""

    def __init__(self, download_url: str = "https://speed.hetzner.de/100MB.bin",
                 upload_url: Optional[str] = None, latency_target: str = "8.8.8.8"):
        self.download_url = download_url
        self.upload_url = upload_url
        self.latency_target = latency_target

    def measure(self, timeout: int = 15, download_secs: int = 8) -> ExternalSpeed:
        import time

        import requests

        result = ExternalSpeed()
        # 延迟
        try:
            from .diagnostics import ping

            pr = ping(self.latency_target, count=4, timeout=2)
            result.latency_ms = pr.avg_ms or 0.0
            result.loss_percent = pr.loss_percent
        except Exception:  # noqa: BLE001
            result.latency_ms = 0.0
        # 下载吞吐：边流式下载边累加字节，到达 download_secs 即停止采样（而非下完整个文件）
        try:
            start = time.time()
            dl_bytes = 0
            with requests.get(self.download_url, stream=True, timeout=timeout) as r:
                for chunk in r.iter_content(chunk_size=65536):
                    dl_bytes += len(chunk)
                    if time.time() - start >= download_secs:
                        break
            # 速率 = 字节 * 8 / 1e6 / 秒，下界 0.001 秒避免除零
            el = max(time.time() - start, 0.001)
            result.download_mbps = round((dl_bytes * 8) / 1_000_000 / el, 2)
            result.success = True
        except Exception as exc:  # noqa: BLE001
            result.note = f"下载测速失败：{exc}"
        # 上行（可选）
        if self.upload_url:
            try:
                payload = b"x" * 1_000_000
                start = time.time()
                requests.post(self.upload_url, data=payload, timeout=timeout)
                el = max(time.time() - start, 0.001)
                result.upload_mbps = round((len(payload) * 8) / 1_000_000 / el, 2)
            except Exception:  # noqa: BLE001
                pass
        return result
