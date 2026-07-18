"""专项排障引擎（core/troubleshoot.py）。

覆盖：ARP 表解析（多厂商）、IP 冲突检测、DHCP 地址池解析与冲突检测、
生成树（STP）解析与环路/异常检测。纯 Python 引擎层，禁止 import PySide6。
重依赖 netmiko 仅在 collect_and_analyze / collect_dhcp 内惰性导入，缺失时抛清晰错误。

返回结构化数据（dict / list），由 gui 渲染，便于单测。
"""

from __future__ import annotations

import ipaddress
import re
from collections import defaultdict
from typing import Dict, List, Optional

# 厂商 -> netmiko device_type
_VENDOR_DEVICE_TYPE = {
    "cisco": "cisco_ios",
    "huawei": "huawei_vrp",
    "h3c": "hp_comware",
    "juniper": "juniper_junos",
}

# 厂商 -> 采集命令
ARP_CMD = {
    "cisco": "show ip arp",
    "huawei": "display arp",
    "h3c": "display arp",
    "juniper": "show arp",
}
STP_CMD = {
    "cisco": "show spanning-tree",
    "huawei": "display stp",
    "h3c": "display stp",
    "juniper": "show spanning-tree",
}
DHCP_CMD = {
    "cisco": "show ip dhcp pool",
    "huawei": "display ip pool",
    "h3c": "display ip pool",
    "juniper": "show system services dhcp pool",
}


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _norm_vendor(vendor: str) -> str:
    v = (vendor or "").lower().strip()
    if "huawei" in v:
        return "huawei"
    if "h3c" in v or "comware" in v:
        return "h3c"
    if "juniper" in v:
        return "juniper"
    if "cisco" in v:
        return "cisco"
    return v


def _norm_mac(mac: str) -> str:
    """规范化 MAC：去分隔符（: - .）并转小写，便于同一 MAC 的跨格式比较。"""
    if not mac:
        return ""
    return re.sub(r"[:.\-]", "", mac).lower()


def _ip_to_int(ip: str) -> int:
    """将点分十进制 IPv4 转为 32 位整数（便于地址范围比较 / 重叠计算）。"""
    parts = [int(x) for x in ip.split(".")]
    return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]


_MAC_RE = (
    r"(?:[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}"
    r"|[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"|[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})"
)
_IP_RE = r"\d{1,3}(?:\.\d{1,3}){3}"


# --------------------------------------------------------------------------
# ARP 表解析（多厂商）
# --------------------------------------------------------------------------
def parse_arp_table(vendor: str, text: str) -> List[Dict[str, str]]:
    """解析 show arp / display arp 输出，返回 [{"ip","mac","interface"}]。

    支持：Cisco IOS（show ip arp）、Huawei VRP（display arp）、
    H3C Comware（display arp）、Juniper JunOS（show arp）。
    """
    v = _norm_vendor(vendor)
    entries: List[Dict[str, str]] = []
    for line in (text or "").splitlines():
        e = _parse_arp_line(v, line)
        if e:
            entries.append(e)
    return entries


def _parse_arp_line(vendor: str, line: str) -> Optional[Dict[str, str]]:
    if vendor == "cisco":
        m = re.match(
            rf"^\s*Internet\s+({_IP_RE})\s+\S+\s+"
            rf"([0-9a-fA-F]{{4}}\.[0-9a-fA-F]{{4}}\.[0-9a-fA-F]{{4}})\s+\S+\s+(\S+)",
            line,
        )
        if m:
            return {"ip": m.group(1), "mac": m.group(2), "interface": m.group(3)}
    elif vendor == "huawei":
        m = re.match(
            rf"^\s*({_IP_RE})\s+([0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}})\s+"
            rf"\S+\s+\S+\s+(\S+)",
            line,
        )
        if m:
            return {"ip": m.group(1), "mac": m.group(2), "interface": m.group(3)}
    elif vendor == "h3c":
        m = re.match(
            rf"^\s*({_IP_RE})\s+([0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}}-[0-9a-fA-F]{{4}})\s+"
            rf"\S+\s+(\S+)",
            line,
        )
        if m:
            return {"ip": m.group(1), "mac": m.group(2), "interface": m.group(3)}
    elif vendor == "juniper":
        m = re.match(
            rf"^\s*([0-9a-fA-F]{{2}}(?::[0-9a-fA-F]{{2}}){{5}})\s+({_IP_RE})\s+\S+\s+(\S+)\s+\S+",
            line,
        )
        if m:
            return {"ip": m.group(2), "mac": m.group(1), "interface": m.group(3)}

    # 通用兜底：行内同时含 IPv4 与任一格式 MAC 即尝试捕获
    ipm = re.search(rf"({_IP_RE})", line)
    macm = re.search(_MAC_RE, line)
    if ipm and macm:
        after = line[macm.end():].split()
        interface = after[0] if after else ""
        return {"ip": ipm.group(1), "mac": macm.group(0), "interface": interface}
    return None


def detect_ip_conflict(arp_entries: List[Dict[str, str]]) -> List[Dict[str, object]]:
    """检测 IP 冲突：同一 IP 关联了 >1 个不同 MAC（跨格式归一化后比较）。

    返回 [{"ip", "macs":[...], "interfaces":[...]}]。
    """
    by_ip: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for e in arp_entries:
        by_ip[e.get("ip", "")].append(e)

    conflicts: List[Dict[str, object]] = []
    for ip, entries in by_ip.items():
        macs: List[str] = []
        interfaces: List[str] = []
        for e in entries:
            # 用归一化 MAC 去重，避免 "aa:bb:cc" 与 "aabbcc" 被视为不同 MAC
            nm = _norm_mac(e.get("mac", ""))
            if nm and nm not in [_norm_mac(x) for x in macs]:
                macs.append(e.get("mac", ""))
            iface = e.get("interface", "")
            if iface:
                interfaces.append(iface)
        if len(macs) > 1:
            conflicts.append({"ip": ip, "macs": macs, "interfaces": interfaces})
    return conflicts


# --------------------------------------------------------------------------
# DHCP 地址池解析与冲突检测
# --------------------------------------------------------------------------
def parse_dhcp_pool(text: str) -> List[Dict[str, object]]:
    """解析 show ip dhcp pool / display ip pool，返回池信息列表。

    每个池含：name / network / gateway / start / end / lease / utilized。
    """
    pools: List[Dict[str, object]] = []
    lines = (text or "").splitlines()
    blocks: List[str] = []
    cur: Optional[List[str]] = None
    for line in lines:
        if re.match(r"\s*Pool\b", line) or re.match(r"\s*Pool name", line):
            if cur is not None:
                blocks.append("\n".join(cur))
            cur = [line]
        elif cur is not None:
            cur.append(line)
    if cur is not None:
        blocks.append("\n".join(cur))

    for blk in blocks:
        name = ""
        nm = re.search(r"Pool\s+(?:name\s*:?\s*)?([\w.\-]+)", blk)
        if nm:
            name = nm.group(1)

        net = ""
        nm2 = re.search(rf"Network\s+is\s+({_IP_RE})\s*/?\s*({_IP_RE})?", blk)
        if nm2:
            net = nm2.group(1) + (("/" + nm2.group(2)) if nm2.group(2) else "")
        if not net:
            nm3 = re.search(rf"({_IP_RE})\s+mask\s+({_IP_RE})", blk)
            if nm3:
                net = nm3.group(1) + "/" + nm3.group(2)

        gateway = ""
        gm = re.search(r"[Gg]ateway[^\d\n]*?([0-9a-fA-F.:/]+)", blk)
        if gm:
            gateway = gm.group(1)

        start = end = ""
        sm = re.search(rf"start\s+({_IP_RE})\s+end\s+({_IP_RE})", blk, re.I)
        if sm:
            start, end = sm.group(1), sm.group(2)

        lease = ""
        lm = re.search(r"lease\s+(?:time\s+)?(\S+)", blk, re.I)
        if lm:
            lease = lm.group(1)

        utilized: Optional[int] = None
        um = re.search(r"Utilized\s*:?\s*(\d+)", blk)
        if um:
            utilized = int(um.group(1))

        pools.append({
            "name": name, "network": net, "gateway": gateway,
            "start": start, "end": end, "lease": lease, "utilized": utilized,
        })
    return pools


def _pool_bounds(pool: Dict[str, object]):
    """返回 (lo, hi) 整数地址范围；无法解析返回 None。"""
    start = pool.get("start")
    end = pool.get("end")
    if start and end:
        try:
            return _ip_to_int(start), _ip_to_int(end)
        except (ValueError, AttributeError):
            return None
    net = pool.get("network")
    if net:
        try:
            nw = ipaddress.ip_network(str(net), strict=False)
            return int(nw.network_address), int(nw.broadcast_address)
        except (ValueError, TypeError):
            return None
    return None


def detect_dhcp_conflict(pools: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """检测 DHCP 冲突：任意两个地址池的 IP 范围重叠即视为冲突。"""
    conflicts: List[Dict[str, object]] = []
    for i in range(len(pools)):
        for j in range(i + 1, len(pools)):
            bi = _pool_bounds(pools[i])
            bj = _pool_bounds(pools[j])
            if bi is None or bj is None:
                continue
            if bi[0] <= bj[1] and bj[0] <= bi[1]:
                conflicts.append({
                    "pool_a": pools[i].get("name"),
                    "pool_b": pools[j].get("name"),
                    "detail": f"地址范围重叠：{pools[i].get('name')} 与 {pools[j].get('name')}",
                })
    return conflicts


# --------------------------------------------------------------------------
# STP 解析与环路/异常检测
# --------------------------------------------------------------------------
def parse_spanning_tree(text: str) -> Dict[str, object]:
    """解析 show spanning-tree / display stp，返回 {"root","blocked_ports":[...]}。

    - root：根桥 MAC（Cisco `Root ID / Address`，Huawei `CIST Root ...`）。
    - blocked_ports：处于 BLK / BKN* / DISCARDING / ALTN 状态的端口。
    """
    root: Optional[str] = None
    m = re.search(r"Root\s+ID.*?Address\s+([0-9a-fA-F.:-]+)", text, re.S)
    if not m:
        m = re.search(r"CIST\s+Root.*?([0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4})", text)
    if not m:
        m = re.search(r"Root\s+Bridge\s+Address\s+([0-9a-fA-F.:-]+)", text)
    if m:
        root = m.group(1)

    blocked_ports: List[str] = []
    for line in (text or "").splitlines():
        mm = re.match(r"^\s*(\S+)\s+\S+\s+(BLK|BKN\*|DISC|ALTN)\b", line)
        if mm:
            blocked_ports.append(mm.group(1))
            continue
        if re.search(r"\bDISCARDING\b", line):
            toks = line.split()
            if toks:
                blocked_ports.append(toks[0])

    return {"root": root, "blocked_ports": blocked_ports}


def detect_loop(arp_entries: Optional[List[Dict[str, str]]] = None,
                stp_info: Optional[Dict[str, object]] = None) -> List[Dict[str, object]]:
    """检测环路/STP 异常。

    当前覆盖：
    - mac_flap：同一 MAC 出现在 >1 个接口（ARP 表），疑似环路或 MAC 漂移。
    - no_root：STP 未识别到根桥（拓扑缺失或解析失败）。
    """
    arp_entries = arp_entries or []
    stp_info = stp_info or {}
    anomalies: List[Dict[str, object]] = []

    by_mac: Dict[str, List[str]] = defaultdict(list)
    for e in arp_entries:
        nm = _norm_mac(e.get("mac", ""))
        if not nm:
            continue
        iface = e.get("interface", "")
        if iface and iface not in by_mac[nm]:
            by_mac[nm].append(iface)
    for mac, ifaces in by_mac.items():
        if len(ifaces) > 1:
            anomalies.append({
                "type": "mac_flap",
                "detail": f"MAC {mac} 出现在多个接口：{', '.join(ifaces)}，疑似环路或 MAC 漂移",
                "mac": mac,
                "port": ", ".join(ifaces),
            })

    if isinstance(stp_info, dict):
        root = stp_info.get("root")
        if root in (None, ""):
            anomalies.append({
                "type": "no_root",
                "detail": "未识别到 STP 根桥，可能拓扑缺失或解析失败",
                "mac": "",
                "port": "",
            })
    return anomalies


# --------------------------------------------------------------------------
# 实时采集（netmiko 惰性导入，清晰降级）
# --------------------------------------------------------------------------
def _resolve_device_type(vendor: str) -> str:
    v = _norm_vendor(vendor)
    if v not in _VENDOR_DEVICE_TYPE:
        raise ValueError(
            f"不支持的厂商：{vendor}（可选：cisco / huawei / h3c / juniper）"
        )
    return _VENDOR_DEVICE_TYPE[v]


def _connect(creds: dict, device_type: str):
    try:
        from netmiko import ConnectHandler
    except ImportError:
        raise RuntimeError(
            "缺少 netmiko，请先 `pip install netmiko` 后再执行设备连接类排障操作"
        )
    return ConnectHandler(
        device_type=device_type,
        host=creds.get("host", "") or creds.get("device", ""),
        username=creds.get("username", ""),
        password=creds.get("password", ""),
        secret=creds.get("secret", ""),
    )


def collect_and_analyze(device: str, creds: dict, vendor: str) -> Dict[str, object]:
    """连接设备，取 ARP 与 STP 并跑分析（IP 冲突 / STP 环路异常）。

    creds 需含 host/username/password/vendor（secret 可选）。
    返回含 arp_entries / ip_conflicts / stp / stp_anomalies 等字段的字典。
    """
    v = _norm_vendor(vendor)
    dt = _resolve_device_type(vendor)
    conn = _connect(creds, dt)
    try:
        conn.enable()
        arp_text = conn.send_command(ARP_CMD[v])
        stp_text = conn.send_command(STP_CMD[v])
    finally:
        conn.disconnect()

    arp_entries = parse_arp_table(v, arp_text)
    ip_conflicts = detect_ip_conflict(arp_entries)
    stp_info = parse_spanning_tree(stp_text)
    stp_anomalies = detect_loop(arp_entries, stp_info)
    return {
        "device": device,
        "vendor": vendor,
        "arp_entries": arp_entries,
        "arp_raw": arp_text,
        "ip_conflicts": ip_conflicts,
        "stp": stp_info,
        "stp_raw": stp_text,
        "stp_anomalies": stp_anomalies,
    }


def collect_dhcp(device: str, creds: dict, vendor: str) -> Dict[str, object]:
    """连接设备，取 DHCP 地址池并跑冲突检测。"""
    v = _norm_vendor(vendor)
    dt = _resolve_device_type(vendor)
    conn = _connect(creds, dt)
    try:
        conn.enable()
        dhcp_text = conn.send_command(DHCP_CMD[v])
    finally:
        conn.disconnect()

    pools = parse_dhcp_pool(dhcp_text)
    conflicts = detect_dhcp_conflict(pools)
    return {
        "device": device,
        "vendor": vendor,
        "dhcp_raw": dhcp_text,
        "dhcp_pools": pools,
        "dhcp_conflicts": conflicts,
    }
