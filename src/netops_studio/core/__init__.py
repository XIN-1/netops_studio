"""核心引擎层。

约定：本层**禁止 import PySide6 / 任何 GUI 依赖**，保证可单测、可未来 Web 复用。
模块通过纯函数 / dataclass 返回结构化结果，由 GUI 层负责渲染。
"""

from .subnet import SubnetResult, calculate, subnet_split, ip_in_network
from .codec import (
    base64_encode, base64_decode, url_encode, url_decode,
    hash_data, jwt_parse, timestamp_convert, pem_parse,
)
from .diagnostics import (
    PingResult, TracerouteHop, TraceResult, PortScanResult,
    ping, traceroute, port_scan, dns_query, http_probe,
)
from .discovery import Host, scan_network
from .speedtest import Iperf3Server, Iperf3Client, SpeedResult, ExternalTester

__all__ = [
    "SubnetResult", "calculate", "subnet_split", "ip_in_network",
    "base64_encode", "base64_decode", "url_encode", "url_decode",
    "hash_data", "jwt_parse", "timestamp_convert", "pem_parse",
    "PingResult", "TracerouteHop", "TraceResult", "PortScanResult",
    "ping", "traceroute", "port_scan", "dns_query", "http_probe",
    "Host", "scan_network",
    "Iperf3Server", "Iperf3Client", "SpeedResult", "ExternalTester",
]
