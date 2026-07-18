"""连通性诊断引擎（core/diagnostics.py）。

参考开发文档 §6.3。命令统一走适配层（platform.system() 分支），不得硬编码平台路径。
全部返回结构化 dataclass，由 GUI 渲染。
"""

from __future__ import annotations

import platform
import socket
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

_SYSTEM = platform.system().lower()


@dataclass
class PingResult:
    target: str
    transmitted: int = 0
    received: int = 0
    loss_percent: float = 0.0
    min_ms: Optional[float] = None
    avg_ms: Optional[float] = None
    max_ms: Optional[float] = None
    raw: str = ""
    success: bool = False


@dataclass
class TracerouteHop:
    hop: int
    host: str
    ip: str
    rtt_ms: Optional[float]


@dataclass
class TraceResult:
    target: str
    hops: List[TracerouteHop] = field(default_factory=list)
    raw: str = ""
    success: bool = False


@dataclass
class PortScanResult:
    target: str
    port: int
    state: str  # open / closed / filtered
    service: str = ""
    error: str = ""


# --------------------------------------------------------------------------
# ping
# --------------------------------------------------------------------------
def ping(target: str, count: int = 4, timeout: int = 2) -> PingResult:
    if _SYSTEM == "windows":
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), target]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), target]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * count + 10)
        raw = out.stdout + out.stderr
    except subprocess.TimeoutExpired:
        return PingResult(target=target, raw="命令超时", success=False)
    return _parse_ping(target, raw)


def _parse_ping(target: str, raw: str) -> PingResult:
    """解析 ping 命令输出（Windows / 类 Unix 两种格式）为 PingResult。"""
    import re

    res = PingResult(target=target, raw=raw)
    if _SYSTEM == "windows":
        # 已接收 = 4，丢失 = 0 (0% 丢失)
        m = re.search(r"已接收 = (\d+).*?丢失 = (\d+) \((\d+)%", raw)
        if m:
            res.received = int(m.group(1))
            lost = int(m.group(2))
            res.loss_percent = float(m.group(3))
            res.transmitted = res.received + lost
        # 最短 = 10ms，最长 = 12ms，平均 = 11ms
        mn = re.search(r"最短 = (\d+(?:\.\d+)?)ms", raw)
        av = re.search(r"平均 = (\d+(?:\.\d+)?)ms", raw)
        mx = re.search(r"最长 = (\d+(?:\.\d+)?)ms", raw)
        if mn:
            res.min_ms = float(mn.group(1))
        if av:
            res.avg_ms = float(av.group(1))
        if mx:
            res.max_ms = float(mx.group(1))
    else:
        m = re.search(r"(\d+) packets transmitted, (\d+) received", raw)
        if m:
            res.transmitted = int(m.group(1))
            res.received = int(m.group(2))
        lp = re.search(r"(\d+(?:\.\d+)?)% packet loss", raw)
        if lp:
            res.loss_percent = float(lp.group(1))
        else:
            res.loss_percent = round((1 - res.received / res.transmitted) * 100, 1) if res.transmitted else 100.0
        rtt = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)/([\d.]+)", raw)
        if rtt:
            res.min_ms = float(rtt.group(1))
            res.avg_ms = float(rtt.group(2))
            res.max_ms = float(rtt.group(3))
    res.success = res.received > 0
    return res


# --------------------------------------------------------------------------
# traceroute
# --------------------------------------------------------------------------
def traceroute(target: str, max_hops: int = 30, timeout: int = 2) -> TraceResult:
    if _SYSTEM == "windows":
        cmd = ["tracert", "-h", str(max_hops), "-w", str(timeout * 1000), target]
    else:
        cmd = ["traceroute", "-m", str(max_hops), "-w", str(timeout), target]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=max_hops * timeout + 20)
        raw = out.stdout + out.stderr
    except subprocess.TimeoutExpired:
        return TraceResult(target=target, raw="命令超时", success=False)
    return _parse_traceroute(target, raw)


def _parse_traceroute(target: str, raw: str) -> TraceResult:
    """解析 traceroute/tracert 输出为 TraceResult（逐跳提取 IP 与 RTT）。"""
    res = TraceResult(target=target, raw=raw)
    # 注：本文件未在顶层 import re，此处通过 __import__("re") 取得标准库模块引用，
    # 与 _parse_ping 中的 `import re` 风格不一致，建议后续统一为顶层 import。
    re = __import__("re")
    for line in raw.splitlines():
        m = re.match(r"\s*(\d+)\s+(.+)", line)
        if not m:
            continue
        hop = int(m.group(1))
        rest = m.group(2)
        # 提取 IP（* 表示超时）
        ipm = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", rest)
        rttm = re.findall(r"(\d+(?:\.\d+)?)\s*ms", rest)
        ip = ipm.group(1) if ipm else ("*" if "*" in rest else "")
        host = rest.split()[0] if rest.split() and rest.split()[0] != ip else ip
        rtt = float(rttm[0]) if rttm else None
        res.hops.append(TracerouteHop(hop=hop, host=host, ip=ip, rtt_ms=rtt))
    res.success = len(res.hops) > 0
    return res


# --------------------------------------------------------------------------
# 端口扫描（并发 socket 探测 TCP）
# --------------------------------------------------------------------------
import concurrent.futures


def port_scan(target: str, ports, timeout: float = 0.5) -> List[PortScanResult]:
    if isinstance(ports, int):
        ports = [ports]
    elif isinstance(ports, str):
        ports = _expand_ports(ports)

    def probe(port: int) -> PortScanResult:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                code = s.connect_ex((target, port))
                state = "open" if code == 0 else "closed"
                svc = ""
                if state == "open":
                    try:
                        svc = socket.getservbyport(port)
                    except OSError:
                        svc = ""
                return PortScanResult(target=target, port=port, state=state, service=svc)
        except Exception as exc:  # noqa: BLE001
            return PortScanResult(target=target, port=port, state="filtered", error=str(exc))

    results: List[PortScanResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as ex:
        results = list(ex.map(probe, ports))
    results.sort(key=lambda r: r.port)
    return results


def _expand_ports(spec: str) -> List[int]:
    """将 "22,80,100-110" 形式的端口规格展开为整数列表（含区间端点）。"""
    ports: List[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            ports.extend(range(int(a), int(b) + 1))
        elif part:
            ports.append(int(part))
    return ports


# --------------------------------------------------------------------------
# DNS / HTTP 探测
# --------------------------------------------------------------------------
def dns_query(name: str, rdtype: str = "A", nameserver: Optional[str] = None) -> dict:
    try:
        import dns.resolver  # 可选依赖，延迟导入以免污染 core 顶层
    except ImportError:
        return {"name": name, "type": rdtype, "records": [],
                "success": False, "error": "缺少 dnspython，请 pip install dnspython"}
    try:
        res = dns.resolver.Resolver()
        if nameserver:
            res.nameservers = [nameserver]
        answer = res.resolve(name, rdtype)
        records = [r.to_text() for r in answer]
        return {"name": name, "type": rdtype, "records": records, "success": True}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "type": rdtype, "records": [], "success": False, "error": str(exc)}


def http_probe(url: str, timeout: int = 5) -> dict:
    import requests

    try:
        r = requests.get(url, timeout=timeout, allow_redirects=True)
        return {
            "url": url,
            "status_code": r.status_code,
            "ok": r.ok,
            "elapsed_ms": round(r.elapsed.total_seconds() * 1000, 1),
            "final_url": r.url,
            "server": r.headers.get("Server", ""),
            "content_type": r.headers.get("Content-Type", ""),
            "content_length": r.headers.get("Content-Length", ""),
            "success": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "success": False, "error": str(exc)}
