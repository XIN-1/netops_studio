"""抓包分析引擎（core/capture.py）。

参考开发文档 §6.x。封装 tshark（随包二进制，resources/bin/<os>/tshark，否则系统 PATH）。
约定：
- 本模块**禁止 import PySide6 / 任何 GUI 依赖**，保证可单测、可复用。
- tshark 二进制惰性查找（find_tshark），缺失抛清晰错误，绝不静默降级。
- 解析函数（parse_conversations / protocol_stats / detect_anomalies）为纯函数，
  输入为 tshark 文本输出，不依赖外部二进制，便于单测。
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from typing import Dict, List, Optional

_SYSTEM = platform.system().lower()

# 平台 -> resources 自带 tshark 相对路径（相对 src/netops_studio）
_RESOURCE_BIN = {
    "windows": "resources/bin/windows/tshark.exe",
    "linux": "resources/bin/linux/tshark",
    "darwin": "resources/bin/macos/tshark",
}

# 异常检测阈值（可经参数覆盖）
DEFAULT_DOMINANCE_THRESHOLD = 0.5   # 单 IP 字节占比超过该比例视为异常
DEFAULT_FANOUT_THRESHOLD = 20      # 单源与超过该数量的不同目标通信视为异常（疑似扫描/ARP 风暴）

# 参与会话统计的协议（均为 L3/L2，互不重叠，避免重复计数）
_CONV_PROTOCOLS = ("ip", "ipv6", "arp")


class TsharkNotFoundError(RuntimeError):
    """tshark 二进制未找到时抛出。"""


def _pkg_root() -> str:
    """src/netops_studio 目录（capture.py 的上两级）。"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_tshark(pkg_root: Optional[str] = None) -> str:
    """查找 tshark 可执行文件：优先 resources/bin/<os>/tshark，否则系统 PATH。

    缺失时抛出 TsharkNotFoundError（清晰错误，不静默降级）。
    """
    if pkg_root is None:
        pkg_root = _pkg_root()
    rel = _RESOURCE_BIN.get(_SYSTEM)
    if rel:
        bundled = os.path.join(pkg_root, rel)
        if os.path.isfile(bundled) and os.access(bundled, os.X_OK):
            return bundled
    found = shutil.which("tshark")
    if found:
        return found
    raise TsharkNotFoundError(
        "未找到 tshark：请将 tshark 放入 resources/bin/<os>/ 或将其加入系统 PATH"
    )


def _run(cmd: List[str], timeout: int = 120) -> str:
    """运行子进程并返回合并后的 stdout+stderr 文本。

    超时时返回空串（由上层解析函数优雅降级为空结果），不向上抛异常。
    """
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return ""
    return out.stdout + out.stderr


# --------------------------------------------------------------------------
# 网卡枚举
# --------------------------------------------------------------------------
def list_interfaces() -> List[dict]:
    """`tshark -D` 列举网卡。返回 [{"index","name","description"}]。"""
    bin_path = find_tshark()
    text = _run([bin_path, "-D"], timeout=30)
    return _parse_interfaces(text)


def _parse_interfaces(text: str) -> List[dict]:
    ifaces: List[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 形如：1. eth0   或  2. \Device\NPF_{...} (描述)
        m = re.match(r"^(\d+)\.\s+(.+)$", line)
        if not m:
            continue
        idx = m.group(1)
        rest = m.group(2).strip()
        desc_m = re.search(r"\((.+)\)$", rest)
        if desc_m and rest.endswith(")"):
            name = rest[: desc_m.start()].strip()
            desc = desc_m.group(1).strip()
        else:
            name = rest
            desc = ""
        ifaces.append({"index": idx, "name": name, "description": desc})
    return ifaces


# --------------------------------------------------------------------------
# 抓包
# --------------------------------------------------------------------------
def capture(interface: str, duration: int, outfile: str) -> dict:
    """`tshark -i <iface> -a duration:<d> -w <outfile>` 抓包到文件。"""
    bin_path = find_tshark()
    parent = os.path.dirname(os.path.abspath(outfile))
    os.makedirs(parent, exist_ok=True)
    cmd = [bin_path, "-i", interface, "-a", f"duration:{duration}", "-w", outfile]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 60)
    except subprocess.TimeoutExpired:
        return {
            "interface": interface, "duration": duration, "outfile": outfile,
            "returncode": -1, "raw": "抓包超时", "success": False,
        }
    raw = proc.stdout + proc.stderr
    return {
        "interface": interface,
        "duration": duration,
        "outfile": outfile,
        "returncode": proc.returncode,
        "raw": raw,
        "success": proc.returncode == 0,
    }


# --------------------------------------------------------------------------
# 纯解析函数
# --------------------------------------------------------------------------
def parse_conversations(text: str) -> List[dict]:
    """解析 `tshark -r file -q -z conv,<proto>` 输出。

    返回 [{"src","dst","packets","bytes"}]，packets/bytes 为会话总计。
    会话数据行形如：
      <src>  <->  <dst>   <f<-| b<->| f->| b->| f总| b总| 起始| 时长>
    其中第 8/9 个空白分隔字段即总帧数/总字节数。
    """
    convs: List[dict] = []
    for line in text.splitlines():
        if "<->" not in line:
            continue
        parts = line.split()
        # 期望：src <-> dst  f<-> b<-> f-> b-> f总 b总 relstart duration
        if len(parts) < 9 or parts[1] != "<->":
            continue
        try:
            packets = int(parts[7])
            nbytes = int(parts[8])
        except (ValueError, IndexError):
            continue
        convs.append({
            "src": parts[0],
            "dst": parts[2],
            "packets": packets,
            "bytes": nbytes,
        })
    return convs


def protocol_stats(text: str) -> Dict[str, int]:
    """解析 `tshark -r file -q -z io,phs` 协议层级统计。

    返回 {"proto": bytes}。支持缩进嵌套（eth / ip / tcp ...）。
    """
    stats: Dict[str, int] = {}
    pat = re.compile(r"^\s*(\S+)\s+frames:(\d+)\s+bytes:(\d+)")
    for line in text.splitlines():
        m = pat.search(line)
        if not m:
            continue
        proto = m.group(1)
        nbytes = int(m.group(3))
        stats[proto] = stats.get(proto, 0) + nbytes
    return stats


def detect_anomalies(
    records: List[dict],
    dominance_threshold: float = DEFAULT_DOMINANCE_THRESHOLD,
    fanout_threshold: int = DEFAULT_FANOUT_THRESHOLD,
) -> List[dict]:
    """基于会话记录检测异常。

    异常类型：
    - single_ip_dominance：单 IP 字节占比过高（疑似被抓包/洪泛源）。
    - conversation_fanout：单源与大量不同目标通信（疑似 ARP 风暴 / 端口扫描）。
    返回 [{"type","severity","message","detail"}]。
    """
    anomalies: List[dict] = []
    if not records:
        return anomalies

    # 单 IP 字节占比：将每个会话的字节数按端点（src 与 dst）双向累加，
    # 再计算该 IP 占全部流量的比例（total_bytes==0 时跳过，避免除零）。
    total_bytes = sum(int(r.get("bytes", 0) or 0) for r in records)
    if total_bytes > 0:
        per_ip: Dict[str, int] = {}
        for r in records:
            for ep in (r.get("src"), r.get("dst")):
                if ep is None:
                    continue
                per_ip[ep] = per_ip.get(ep, 0) + int(r.get("bytes", 0) or 0)
        for ip, b in per_ip.items():
            ratio = b / total_bytes
            if ratio >= dominance_threshold:
                anomalies.append({
                    "type": "single_ip_dominance",
                    "severity": "high" if ratio >= 0.8 else "medium",
                    "message": f"单 IP 流量占比过高：{ip} 占 {ratio * 100:.1f}%",
                    "detail": {"ip": ip, "bytes": b, "ratio": round(ratio, 3)},
                })

    # 会话扇出（单源 -> 多个不同目标）
    fanout: Dict[str, set] = {}
    for r in records:
        src = r.get("src")
        dst = r.get("dst")
        if src is None or dst is None:
            continue
        fanout.setdefault(src, set()).add(dst)
    for ip, dsts in fanout.items():
        if len(dsts) >= fanout_threshold:
            anomalies.append({
                "type": "conversation_fanout",
                "severity": "high" if len(dsts) >= fanout_threshold * 2 else "medium",
                "message": f"疑似 ARP 风暴/端口扫描：{ip} 与 {len(dsts)} 个目标通信",
                "detail": {"ip": ip, "distinct_dst": len(dsts)},
            })

    return anomalies


# --------------------------------------------------------------------------
# 聚合分析（调用 tshark 子进程）
# --------------------------------------------------------------------------
def analyze_pcap(pcap: str) -> dict:
    """读取 pcap 文件，聚合 会话 / 协议分布 / 异常 三类结果。

    缺失 tshark 时由 find_tshark 抛清晰错误。文件不存在抛 FileNotFoundError。
    """
    _ = find_tshark()  # 提前校验，缺失抛清晰错误
    if not os.path.isfile(pcap):
        raise FileNotFoundError(f"pcap 文件不存在：{pcap}")

    conv_text = ""
    for proto in _CONV_PROTOCOLS:
        conv_text += _run([
            find_tshark(), "-r", pcap, "-q", "-z", f"conv,{proto}"
        ], timeout=120)
    phs_text = _run([
        find_tshark(), "-r", pcap, "-q", "-z", "io,phs"
    ], timeout=120)

    conversations = parse_conversations(conv_text)
    protocols = protocol_stats(phs_text)
    anomalies = detect_anomalies(conversations)

    return {
        "pcap": pcap,
        "conversations": conversations,
        "protocols": protocols,
        "anomalies": anomalies,
    }
