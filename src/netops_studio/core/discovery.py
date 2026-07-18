"""网络发现引擎（core/discovery.py）。

参考开发文档 §6.2。多线程 ping 扫描目标网段，解析 IP / 主机名 / MAC。
通过回调 on_progress / on_host 实时回传，便于 GUI 经 EventBus 渲染。
"""

from __future__ import annotations

import ipaddress
import platform
import re
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, List, Optional

_SYSTEM = platform.system().lower()


@dataclass
class Host:
    """一次扫描发现的存活主机（含尽力解析的主机名 / MAC / 厂商）。"""

    ip: str
    hostname: str = ""
    mac: str = ""
    vendor: str = ""
    state: str = "up"
    latency_ms: Optional[float] = None


def scan_network(
    cidr: str,
    on_progress: Optional[Callable[[int, int], None]] = None,
    on_host: Optional[Callable[[Host], None]] = None,
    workers: int = 64,
    timeout: int = 1,
) -> List[Host]:
    """扫描一个网段，返回存活主机列表。

    Args:
        cidr: 目标网段，如 "192.168.1.0/24"
        on_progress: 进度回调 (done, total)
        on_host: 发现存活主机的回调
        workers: 并发 ping 数
        timeout: 单主机 ping 超时（秒）
    """
    net = ipaddress.ip_network(cidr.strip(), strict=False)
    hosts_to_scan = list(net.hosts())
    total = len(hosts_to_scan)
    found: List[Host] = []
    done = 0

    def probe(ip: str) -> Optional[Host]:
        from .diagnostics import ping

        # 跳过网络/广播地址本身
        if ip == str(net.network_address) or (net.version == 4 and ip == str(net.broadcast_address)):
            return None
        pr = ping(ip, count=1, timeout=timeout)
        if pr.received > 0:
            return _enrich(Host(ip=ip, latency_ms=pr.avg_ms))
        return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for host in ex.map(probe, [str(ip) for ip in hosts_to_scan]):
            done += 1
            if on_progress:
                on_progress(done, total)
            if host is not None:
                if on_host:
                    on_host(host)
                found.append(host)
    return found


def _enrich(host: Host) -> Host:
    """补充主机名与 MAC/厂商信息（尽力而为，失败不影响存活判定）。"""
    # 主机名：反向 DNS 解析，失败则留空
    try:
        host.hostname = socket.gethostbyaddr(host.ip)[0]
    except Exception:  # noqa: BLE001
        host.hostname = ""
    # MAC（尽力而为，需权限）：解析失败则以 ("", "") 兜底
    host.mac, host.vendor = _resolve_mac(host.ip)
    return host


def _resolve_mac(ip: str) -> (str, str):
    """解析指定 IP 的 MAC 与厂商（OUI）。返回 (mac, vendor)，查不到则 ("", "")。

    注：返回标注 (str, str) 为旧式元组注解（等价于 tuple[str, str]）。
    """
    try:
        if _SYSTEM == "windows":
            out = subprocess.run(["arp", "-a", ip], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"([0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}", out)
        else:
            # linux: ip neigh 或 arp -n
            try:
                out = subprocess.run(["ip", "neigh", "show", ip], capture_output=True, text=True, timeout=5).stdout
            except FileNotFoundError:
                out = subprocess.run(["arp", "-n", ip], capture_output=True, text=True, timeout=5).stdout
            m = re.search(r"([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", out)
        if m:
            mac = m.group(0)
            return mac, _oui_lookup(mac)
    except Exception:  # noqa: BLE001
        pass
    return "", ""


def _oui_lookup(mac: str) -> str:
    """根据 MAC 前 3 字节（OUI）粗略判断厂商（内嵌小型表，未知返回空串）。"""
    oui = mac.replace("-", "").replace(":", "").upper()[:6]
    table = {
        "000C29": "VMware",
        "001C14": "Dell",
        "001A2B": "Cisco",
        "001B21": "Cisco",
        "F44CAB": "Cisco",
        "AC1F6B": "Huawei",
        "3C970F": "Huawei",
        "00E0FC": "Huawei",
        "000FE2": "H3C",
        "20F41B": "H3C",
        "001A4B": "Juniper",
        "B0C504": "Apple",
        "3C22FB": "Apple",
        "FCA667": "Apple",
        "9C93E4": "Huawei",
    }
    return table.get(oui, "")
