"""流量深度分析引擎（core/flow.py）。

解析 NetFlow / sFlow / IPFIX 导出的 JSON / CSV 记录，提供 Top Talkers、
应用占比、异常检测等纯函数。本层禁止 import PySide6 / 任何 GUI 依赖，
结果全部以 dataclass / dict 返回，由 gui 层渲染。参考文档 §6.x。
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Dict, List, Optional

# 1,000,000 字节 = 1 MB（流量统计常用十进制，区别于二进制 MiB=1048576）
MB = 1_000_000


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------
@dataclass
class FlowRecord:
    src: str = ""
    dst: str = ""
    src_port: int = 0
    dst_port: int = 0
    protocol: str = ""          # 标准化后的协议名：TCP / UDP / ICMP / OTHER
    bytes: int = 0
    packets: int = 0

    @property
    def endpoint(self) -> str:
        """可读的端到端描述，用于表格展示。"""
        return f"{self.src}:{self.src_port} → {self.dst}:{self.dst_port}"


# --------------------------------------------------------------------------
# 协议标准化
# --------------------------------------------------------------------------
_PROTO_NUM = {1: "ICMP", 2: "IGMP", 6: "TCP", 17: "UDP", 47: "GRE", 50: "ESP", 51: "AH"}


def _norm_protocol(value) -> str:
    """将协议（数字或名称）统一为可读名。"""
    if value is None:
        return "OTHER"
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return _PROTO_NUM.get(int(value), f"PROTO{int(value)}")
    s = str(value).strip().upper()
    if s in _PROTO_NUM.values():
        return s
    return s or "OTHER"


# 常见端口 -> 应用名（按 TCP/UDP 通用）
_PORT_APP = {
    20: "FTP", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
    53: "DNS", 67: "DHCP", 68: "DHCP", 69: "TFTP", 80: "HTTP",
    110: "POP3", 123: "NTP", 137: "NetBIOS", 138: "NetBIOS",
    139: "NetBIOS", 143: "IMAP", 161: "SNMP", 162: "SNMP",
    179: "BGP", 389: "LDAP", 443: "HTTPS", 445: "SMB",
    465: "SMTPS", 514: "Syslog", 587: "SMTP", 636: "LDAPS",
    993: "IMAPS", 995: "POP3S", 1433: "MSSQL", 1521: "Oracle",
    3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 5900: "VNC",
    6379: "Redis", 8080: "HTTP-ALT", 8443: "HTTPS-ALT", 9200: "Elastic",
}


def _app_name(protocol: str, dst_port: int, src_port: int = 0) -> str:
    """由协议 + 目的端口（回退源端口）推断应用名，未知则回退协议名。"""
    for port in (dst_port, src_port):
        if port in _PORT_APP:
            return _PORT_APP[port]
    return protocol or "OTHER"


# --------------------------------------------------------------------------
# 字段抽取（兼容多种导出字段别名）
# --------------------------------------------------------------------------
_ADDR_KEYS = ("srcaddr", "src_ip", "source", "src", "src_ip_addr", "sa")
_DADDR_KEYS = ("dstaddr", "dst_ip", "destination", "dst", "dst_ip_addr", "da")
_SPORT_KEYS = ("srcport", "src_port", "sport", "srcport_iana", "l4_src_port")
_DPORT_KEYS = ("dstport", "dst_port", "dport", "dstport_iana", "l4_dst_port")
_PROTO_KEYS = ("protocol", "proto", "prot", "ip_proto", "l4_protocol")
_BYTES_KEYS = ("bytes", "in_bytes", "dOctets", "octets", "ibytes", "obytes", "flows_octets")
_PKTS_KEYS = ("packets", "pkts", "dPkts", "ipkts", "opkts", "flows_pkts")


def _pick(d: dict, keys) -> Optional[object]:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _to_int(v) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _to_bytes(v) -> int:
    """尽量安全转换为字节数（整数）。

    字符串先去除千分位逗号（如 "1,024"）；无法解析（空串 / None / 非数字）时回退 0。
    """
    if isinstance(v, str):
        v = v.replace(",", "").strip()
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _record_from_dict(d: dict) -> Optional[FlowRecord]:
    if not isinstance(d, dict):
        return None
    src = _pick(d, _ADDR_KEYS)
    dst = _pick(d, _DADDR_KEYS)
    if src is None and dst is None:
        return None  # 无端点信息，跳过
    proto_raw = _pick(d, _PROTO_KEYS)
    sport = _to_int(_pick(d, _SPORT_KEYS))
    dport = _to_int(_pick(d, _DPORT_KEYS))
    protocol = _norm_protocol(proto_raw)
    return FlowRecord(
        src=str(src) if src is not None else "",
        dst=str(dst) if dst is not None else "",
        src_port=sport,
        dst_port=dport,
        protocol=protocol,
        bytes=_to_bytes(_pick(d, _BYTES_KEYS)) if _pick(d, _BYTES_KEYS) is not None else 0,
        packets=_to_int(_pick(d, _PKTS_KEYS)),
    )


def _iter_records(obj) -> List[dict]:
    """从解析后的 JSON 对象中提取记录 dict 列表（兼容多种包裹结构）。"""
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict):
        for key in ("flows", "records", "data", "flow_records", "flows_export", "values"):
            val = obj.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
        # 单个对象本身即一条记录
        return [obj]
    return []


# --------------------------------------------------------------------------
# 解析器
# --------------------------------------------------------------------------
def parse_netflow_json(text: str) -> List[FlowRecord]:
    """解析 NetFlow / sFlow / IPFIX 导出的 JSON 文本为 FlowRecord 列表（纯函数）。"""
    text = (text or "").strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc}") from exc
    records: List[FlowRecord] = []
    for d in _iter_records(obj):
        r = _record_from_dict(d)
        if r is not None:
            records.append(r)
    return records


def parse_flow_csv(text: str) -> List[FlowRecord]:
    """解析 CSV 文本为 FlowRecord 列表（纯函数）。首行为表头。"""
    text = text or ""
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    records: List[FlowRecord] = []
    for row in reader:
        norm = {k.lower().strip(): v for k, v in row.items()}
        # 复用 dict 抽取逻辑
        d = {
            "srcaddr": norm.get("srcaddr", norm.get("src", norm.get("source", ""))),
            "dstaddr": norm.get("dstaddr", norm.get("dst", norm.get("destination", ""))),
            "srcport": norm.get("src_port", norm.get("srcport", norm.get("sport", ""))),
            "dstport": norm.get("dst_port", norm.get("dstport", norm.get("dport", ""))),
            "protocol": norm.get("protocol", norm.get("proto", "")),
            "bytes": norm.get("bytes", norm.get("octets", norm.get("dOctets", ""))),
            "packets": norm.get("packets", norm.get("pkts", "")),
        }
        r = _record_from_dict(d)
        if r is not None:
            records.append(r)
    return records


# --------------------------------------------------------------------------
# 分析函数
# --------------------------------------------------------------------------
def top_talkers(records: List[FlowRecord], n: int = 10) -> List[FlowRecord]:
    """按 bytes 降序返回 Top Talkers（最多 n 条）。纯函数。"""
    if records is None:
        return []
    ordered = sorted(records, key=lambda r: r.bytes, reverse=True)
    if n is not None and n >= 0:
        ordered = ordered[:n]
    return ordered


def app_share(records: List[FlowRecord]) -> Dict[str, int]:
    """应用占比：{应用名: 字节数}。纯函数。"""
    share: Dict[str, int] = {}
    if not records:
        return share
    for r in records:
        app = _app_name(r.protocol, r.dst_port, r.src_port)
        share[app] = share.get(app, 0) + r.bytes
    # 按字节降序，便于展示
    return dict(sorted(share.items(), key=lambda kv: kv[1], reverse=True))


def detect_anomalies(records: List[FlowRecord],
                     threshold_mb: float = 100.0,
                     share_limit: float = 0.5) -> List[Dict[str, object]]:
    """检测流量异常：超大单流（流量突增）+ 单流占比异常。纯函数。

    返回 list[dict]，每条含：
        type    - '大流量单流' / '单流占比异常'
        src/dst - 端点
        bytes   - 该流字节数
        detail  - 人类可读说明
    """
    anomalies: List[Dict[str, object]] = []
    if not records:
        return anomalies
    total = sum(r.bytes for r in records)
    thr_bytes = threshold_mb * MB

    for r in records:
        # 1) 超大单流（疑似流量突增）
        if r.bytes > thr_bytes:
            anomalies.append({
                "type": "大流量单流",
                "src": r.src,
                "dst": r.dst,
                "bytes": r.bytes,
                "detail": (
                    f"{r.endpoint} 流量 {r.bytes / MB:.2f} MB "
                    f"超过阈值 {threshold_mb:.1f} MB"
                ),
            })
        # 2) 单流占比异常（占总流量过高）
        if total > 0 and (r.bytes / total) > share_limit:
            anomalies.append({
                "type": "单流占比异常",
                "src": r.src,
                "dst": r.dst,
                "bytes": r.bytes,
                "detail": (
                    f"{r.endpoint} 占总流量 "
                    f"{r.bytes / total * 100:.1f}%（阈值 {share_limit * 100:.0f}%）"
                ),
            })
    return anomalies


# --------------------------------------------------------------------------
# 文件载入（纯函数，GUI 经 AsyncWorker 调用）
# --------------------------------------------------------------------------
def import_flow(path: str) -> List[FlowRecord]:
    """从 JSON / CSV 文件载入 FlowRecord 列表。

    依据扩展名选择解析器；读取与解析均在调用线程完成（适合 AsyncWorker）。
    """
    import os

    if not os.path.isfile(path):
        raise FileNotFoundError(f"文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return parse_flow_csv(text)
    # 默认按 JSON 处理
    return parse_netflow_json(text)
