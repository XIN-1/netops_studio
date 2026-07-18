"""监控与告警引擎（core/monitor.py）。

职责：MIB 浏览、SNMP 采集（pysnmp 惰性导入）、阈值判定、Syslog 接收与解析、
Trap 文本解析、趋势统计。纯 Python，禁止 import PySide6 / Qt。
所有对外结果以 dataclass / dict 返回，由 gui 层渲染。参考文档 §6.x。
"""

from __future__ import annotations

import re
import socket
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


# --------------------------------------------------------------------------
# 常见 MIB OID 表
# --------------------------------------------------------------------------
COMMON_OIDS: List[Dict[str, str]] = [
    {"name": "系统运行时间", "oid": "1.3.6.1.2.1.1.3.0", "mib": "SNMPv2-MIB::sysUpTime.0"},
    {"name": "系统描述", "oid": "1.3.6.1.2.1.1.1.0", "mib": "SNMPv2-MIB::sysDescr.0"},
    {"name": "系统名称", "oid": "1.3.6.1.2.1.1.5.0", "mib": "SNMPv2-MIB::sysName.0"},
    {"name": "系统联系人", "oid": "1.3.6.1.2.1.1.4.0", "mib": "SNMPv2-MIB::sysContact.0"},
    {"name": "系统位置", "oid": "1.3.6.1.2.1.1.6.0", "mib": "SNMPv2-MIB::sysLocation.0"},
    {"name": "接口入流量", "oid": "1.3.6.1.2.1.2.2.1.10", "mib": "IF-MIB::ifInOctets"},
    {"name": "接口出流量", "oid": "1.3.6.1.2.1.2.2.1.16", "mib": "IF-MIB::ifOutOctets"},
    {"name": "接口描述", "oid": "1.3.6.1.2.1.2.2.1.2", "mib": "IF-MIB::ifDescr"},
    {"name": "接口状态", "oid": "1.3.6.1.2.1.2.2.1.8", "mib": "IF-MIB::ifOperStatus"},
    {"name": "CPU 负载(1min)", "oid": "1.3.6.1.4.1.2021.10.1.3.1", "mib": "UCD-SNMP-MIB::laLoad.1"},
    {"name": "内存总量", "oid": "1.3.6.1.4.1.2021.4.5.0", "mib": "UCD-SNMP-MIB::memTotalReal.0"},
    {"name": "内存空闲", "oid": "1.3.6.1.4.1.2021.4.6.0", "mib": "UCD-SNMP-MIB::memAvailReal.0"},
    {"name": "磁盘占用率", "oid": "1.3.6.1.4.1.2021.9.1.9.1", "mib": "UCD-SNMP-MIB::dskPercent.1"},
    {"name": "系统进程数", "oid": "1.3.6.1.4.1.2021.2.1.0", "mib": "UCD-SNMP-MIB::ssSystemStats"},
    {"name": "hrSystem 进程数", "oid": "1.3.6.1.2.1.25.1.6.0", "mib": "HOST-RESOURCES-MIB::hrSystemProcesses.0"},
    {"name": "hrSystem 在线用户", "oid": "1.3.6.1.2.1.25.1.5.0", "mib": "HOST-RESOURCES-MIB::hrSystemNumUsers.0"},
]


# --------------------------------------------------------------------------
# 阈值规则
# --------------------------------------------------------------------------
@dataclass
class ThresholdRule:
    metric: str
    op: str            # one of: >, <, >=, <=, ==
    value: float
    severity: str = "crit"   # warn / crit


# 合法比较运算符
_OPS = (">", "<", ">=", "<=", "==")
_STATUSES = ("ok", "warn", "crit")


def evaluate(value: float, rule: ThresholdRule) -> str:
    """纯函数：根据阈值规则判定状态。越界返回 severity，否则 'ok'。"""
    if rule.op not in _OPS:
        raise ValueError(f"不支持的比较运算符: {rule.op!r}（可用: {', '.join(_OPS)}）")
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "warn"
    if rule.op == ">":
        breached = v > rule.value
    elif rule.op == "<":
        breached = v < rule.value
    elif rule.op == ">=":
        breached = v >= rule.value
    elif rule.op == "<=":
        breached = v <= rule.value
    else:  # ==
        breached = v == rule.value
    if not breached:
        return "ok"
    return rule.severity if rule.severity in ("warn", "crit") else "crit"


# --------------------------------------------------------------------------
# SNMP 采集（pysnmp 惰性导入）
# --------------------------------------------------------------------------
def _mp_model(version) -> int:
    if version in (1, "1"):
        return 0      # SNMPv1
    if version in (3, "3"):
        raise RuntimeError("暂不支持 SNMP v3（需要额外的认证配置）")
    return 1          # SNMPv2c（默认）


def snmp_get(target: str, oid: str, community: str = "public", version=2) -> List[Dict[str, str]]:
    """SNMP GET。返回 [{'oid','value','type'}, ...]。缺失 pysnmp 抛清晰错误。"""
    try:
        from pysnmp.hlapi import (  # type: ignore
            CommunityData, ContextData, ObjectIdentity, ObjectType,
            SnmpEngine, UdpTransportTarget, getCmd,
        )
    except ImportError:
        raise RuntimeError("缺少 pysnmp，请执行: pip install pysnmp")

    mp = _mp_model(version)
    try:
        iterator = getCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=mp),
            UdpTransportTarget((target, 161), timeout=2, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
        )
        error_indication, error_status, error_index, var_binds = next(iterator)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"SNMP GET 失败 ({target} {oid}): {exc}")

    if error_indication:
        raise RuntimeError(f"SNMP 错误: {error_indication}")
    if error_status:
        idx = int(error_index) if error_index else 0
        raise RuntimeError(f"SNMP 状态错误: {error_status.prettyPrint()} @ varBind {idx}")
    return [{"oid": str(ob), "value": str(val), "type": type(val).__name__}
            for ob, val in var_binds]


def snmp_walk(target: str, oid: str, community: str = "public", version=2) -> List[Dict[str, str]]:
    """SNMP WALK。返回 [{'oid','value','type'}, ...]。"""
    try:
        from pysnmp.hlapi import (  # type: ignore
            CommunityData, ContextData, ObjectIdentity, ObjectType,
            SnmpEngine, UdpTransportTarget, nextCmd,
        )
    except ImportError:
        raise RuntimeError("缺少 pysnmp，请执行: pip install pysnmp")

    mp = _mp_model(version)
    results: List[Dict[str, str]] = []
    try:
        iterator = nextCmd(
            SnmpEngine(),
            CommunityData(community, mpModel=mp),
            UdpTransportTarget((target, 161), timeout=2, retries=1),
            ContextData(),
            ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        )
        for error_indication, error_status, error_index, var_binds in iterator:
            if error_indication:
                raise RuntimeError(f"SNMP 错误: {error_indication}")
            if error_status:
                idx = int(error_index) if error_index else 0
                raise RuntimeError(f"SNMP 状态错误: {error_status.prettyPrint()} @ varBind {idx}")
            for ob, val in var_binds:
                results.append({"oid": str(ob), "value": str(val), "type": type(val).__name__})
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"SNMP WALK 失败 ({target} {oid}): {exc}")
    return results


# --------------------------------------------------------------------------
# 趋势统计
# --------------------------------------------------------------------------
def trend_stats(series: List[float]) -> Dict[str, Optional[float]]:
    """纯函数：返回序列的 min/max/avg。空序列返回 None 占位。"""
    if not series:
        return {"min": None, "max": None, "avg": None}
    vals = [float(x) for x in series]
    return {"min": min(vals), "max": max(vals), "avg": sum(vals) / len(vals)}


# --------------------------------------------------------------------------
# Syslog 解析（兼容 RFC3164 / RFC5424 基本格式）
# --------------------------------------------------------------------------
_FACILITY_NAMES = {
    0: "kern", 1: "user", 2: "mail", 3: "daemon", 4: "auth", 5: "syslog",
    6: "lpr", 7: "news", 8: "uucp", 9: "cron", 10: "authpriv", 11: "ftp",
    16: "local0", 17: "local1", 18: "local2", 19: "local3",
    20: "local4", 21: "local5", 22: "local6", 23: "local7",
}
_SEVERITY_NAMES = {
    0: "emerg", 1: "alert", 2: "crit", 3: "err", 4: "warning",
    5: "notice", 6: "info", 7: "debug",
}


def parse_syslog(line: str) -> Dict[str, object]:
    """纯函数：解析一行 syslog 为结构化 dict。

    返回键：facility(int), severity(int), host(str), msg(str), ts(str)。
    无 PRI 头或无法识别时间戳时，对应字段给默认值。
    """
    line = (line or "").strip("\r\n")
    facility = -1
    severity = -1
    host = ""
    msg = line
    ts = ""

    m = re.match(r"^<(\d{1,3})>(.*)$", line)
    if m:
        pri = int(m.group(1))
        facility = pri // 8
        severity = pri % 8
        rest = m.group(2)
    else:
        rest = line

    # RFC5424: <pri>VERSION SP TIMESTAMP SP HOSTNAME SP APP SP PROCID SP MSGID SP MSG
    parts = rest.split(" ", 6)
    if len(parts) >= 7 and parts[0] == "1" and re.match(r"\d{4}-\d{2}-\d{2}", parts[1]):
        ts = parts[1]
        host = parts[2]
        msg = parts[6]
        # 去掉 MSGID 后的分隔与 NILVALUE '-' / 结构化数据前缀 '-'
        msg = msg.strip()
        if msg == "-":
            msg = ""
        elif msg.startswith("- "):
            msg = msg[2:].strip()
    else:
        # RFC3164: <pri>Mmm dd HH:MM:SS host msg
        m3164 = re.match(
            r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(\S+)\s+(.*)$", rest
        )
        if m3164:
            ts = m3164.group(1)
            host = m3164.group(2)
            msg = m3164.group(3)
        else:
            msg = rest

    return {
        "facility": facility,
        "severity": severity,
        "host": host,
        "msg": msg,
        "ts": ts,
    }


# --------------------------------------------------------------------------
# Syslog 接收器（后台 UDP 线程）
# --------------------------------------------------------------------------
class SyslogReceiver:
    """UDP syslog 接收器，后台线程收包并回调。

    用法：
        r = SyslogReceiver(port=514, on_message=cb)
        r.start()   # 守护线程监听
        r.stop()
    回调签名：on_message(parsed_dict)，parsed 含 addr 字段。
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 514,
                 on_message: Optional[Callable[[Dict[str, object]], None]] = None) -> None:
        self.host = host
        self.port = port
        self.on_message = on_message
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        self._stop.clear()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind((self.host, self.port))
        except OSError as exc:
            self._sock.close()
            self._sock = None
            raise RuntimeError(f"无法绑定 syslog 端口 {self.port}: {exc}")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        assert self._sock is not None
        self._sock.settimeout(1.0)
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            line = data.decode("utf-8", "replace").rstrip("\r\n")
            parsed = parse_syslog(line)
            parsed["addr"] = addr[0]
            if self.on_message:
                self.on_message(parsed)

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None


# --------------------------------------------------------------------------
# Trap 文本解析（占位实现）
# --------------------------------------------------------------------------
def parse_trap(text: str) -> Dict[str, object]:
    """解析 SNMP Trap 文本（占位：提取 enterprise/agent/oid-value 对）。

    输入通常为 snmptrapd 转发或设备上报的文本。返回结构化 dict。
    """
    text = text or ""
    result: Dict[str, object] = {
        "raw": text,
        "enterprise": "",
        "agent": "",
        "msg": "",
        "oids": [],
    }
    m = re.search(r"enterprise\s*[:=]\s*([\w.\-]+)", text, re.IGNORECASE)
    if m:
        result["enterprise"] = m.group(1)
    m = re.search(r"agent\s*[:=]\s*([\d.]+)", text, re.IGNORECASE)
    if m:
        result["agent"] = m.group(1)
    for m in re.finditer(r"(?:^|\n)\s*([\d.]+)\s*[:=]\s*([^\n\r]+)", text):
        result["oids"].append({"oid": m.group(1), "value": m.group(2).strip()})
    m = re.search(r"message\s*[:=]\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        result["msg"] = m.group(1).strip()
    return result
