"""通用小工具箱（core/toolbox.py）。

纯 Python，仅依赖标准库（ipaddress / secrets / string）。不依赖任何 GUI，
便于单元测试。参考开发文档 §6.x。

提供：掩码↔通配符、OUI 厂商查询、强随机密码、带宽计算、单位换算、
WOL 魔术包构造。
"""

from __future__ import annotations

import ipaddress
import secrets
import string
from typing import Dict

# --------------------------------------------------------------------------
# 掩码 / 通配符互转
# --------------------------------------------------------------------------
def mask_to_wildcard(mask: str) -> str:
    """子网掩码 -> 通配符掩码（按位取反）。支持 IPv4 / IPv6。"""
    addr = ipaddress.ip_address(mask.strip())
    width = addr.max_prefixlen
    wildcard_int = (~int(addr)) & ((1 << width) - 1)
    return str(ipaddress.ip_address(wildcard_int))


def wildcard_to_mask(wildcard: str) -> str:
    """通配符掩码 -> 子网掩码（按位取反）。支持 IPv4 / IPv6。"""
    addr = ipaddress.ip_address(wildcard.strip())
    width = addr.max_prefixlen
    mask_int = (~int(addr)) & ((1 << width) - 1)
    return str(ipaddress.ip_address(mask_int))


# --------------------------------------------------------------------------
# OUI 厂商查询
# --------------------------------------------------------------------------
# 内嵌小型 OUI 表（约 15 条），键为 MAC 前 6 个十六进制字符（大写，无分隔符）。
_OUI_TABLE: Dict[str, str] = {
    "000C29": "VMware",
    "001C14": "Dell",
    "001A2B": "Cisco",
    "001B21": "Cisco",
    "F44CAB": "Cisco",
    "AC1F6B": "Huawei",
    "3C970F": "Huawei",
    "00E0FC": "Huawei",
    "9C93E4": "Huawei",
    "000FE2": "H3C",
    "20F41B": "H3C",
    "001A4B": "Juniper",
    "B0C504": "Apple",
    "3C22FB": "Apple",
    "FCA667": "Apple",
    "001632": "TP-Link",
}


def oui_lookup(mac: str) -> str:
    """根据 MAC 前 3 字节（OUI）粗略判断厂商，未知返回空串。"""
    oui = mac.replace("-", "").replace(":", "").replace(".", "").upper()[:6]
    return _OUI_TABLE.get(oui, "")


# --------------------------------------------------------------------------
# 强随机密码生成
# --------------------------------------------------------------------------
_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?"


def gen_password(
    length: int = 16,
    upper: bool = True,
    lower: bool = True,
    digit: bool = True,
    symbol: bool = True,
) -> str:
    """使用 secrets 强随机生成密码，保证每个启用类别至少出现一次。"""
    pools = []
    if upper:
        pools.append(string.ascii_uppercase)
    if lower:
        pools.append(string.ascii_lowercase)
    if digit:
        pools.append(string.digits)
    if symbol:
        pools.append(_SYMBOLS)
    if not pools:
        raise ValueError("至少需要启用一种字符类型")
    if length < len(pools):
        length = len(pools)

    # 每个启用类别至少取一个字符
    chars = [secrets.choice(pool) for pool in pools]
    all_chars = "".join(pools)
    while len(chars) < length:
        chars.append(secrets.choice(all_chars))

    # Fisher-Yates 洗牌（基于 CSPRNG）
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


# --------------------------------------------------------------------------
# 带宽计算
# --------------------------------------------------------------------------
def bandwidth(size_bytes: float, seconds: float, overhead: float = 1.0) -> float:
    """根据传输字节数与耗时估算速率（Mbps）。

    Mbps = size_bytes * 8 * overhead / seconds / 1e6
    """
    if seconds <= 0:
        raise ValueError("耗时（seconds）必须为正数")
    if overhead <= 0:
        raise ValueError("开销系数（overhead）必须为正数")
    bits = float(size_bytes) * 8.0 * float(overhead)
    return bits / float(seconds) / 1_000_000.0


# --------------------------------------------------------------------------
# 单位换算
# --------------------------------------------------------------------------
# 数据单位：B/KB/MB/GB/TB 为 1000 系；KiB/MiB/GiB/TiB 为 1024 系（基准 = 字节）
_DATA_UNITS: Dict[str, float] = {
    "B": 1.0,
    "KB": 1000.0,
    "MB": 1000.0 ** 2,
    "GB": 1000.0 ** 3,
    "TB": 1000.0 ** 4,
    "KiB": 1024.0,
    "MiB": 1024.0 ** 2,
    "GiB": 1024.0 ** 3,
    "TiB": 1024.0 ** 4,
}

# 速率单位：bps/kbps/Mbps/Gbps 为 1000 系（基准 = bit/s）
_RATE_UNITS: Dict[str, float] = {
    "bps": 1.0,
    "kbps": 1000.0,
    "Mbps": 1000.0 ** 2,
    "Gbps": 1000.0 ** 3,
}


def unit_convert(value: float, from_unit: str, to_unit: str) -> float:
    """数据单位或速率单位之间换算（均基于 1000 系，KiB 等为 1024 系）。

    数据单位与速率单位不可互相转换，否则抛 ValueError。
    """
    fu = (from_unit or "").strip()
    tu = (to_unit or "").strip()
    if fu in _DATA_UNITS and tu in _DATA_UNITS:
        base_bytes = float(value) * _DATA_UNITS[fu]
        return base_bytes / _DATA_UNITS[tu]
    if fu in _RATE_UNITS and tu in _RATE_UNITS:
        base_bits = float(value) * _RATE_UNITS[fu]
        return base_bits / _RATE_UNITS[tu]
    raise ValueError("单位类型不匹配：数据单位与速率单位不可互相转换")


# --------------------------------------------------------------------------
# WOL 魔术包构造
# --------------------------------------------------------------------------
def build_wol(mac: str) -> bytes:
    """构造 Wake-on-LAN 魔术包：6 个 0xFF + 16 次重复 6 字节 MAC（共 102 字节）。"""
    cleaned = mac.replace("-", "").replace(":", "").replace(".", "").upper()
    if len(cleaned) != 12 or not all(c in "0123456789ABCDEF" for c in cleaned):
        raise ValueError("MAC 地址格式不正确")
    mac_bytes = bytes.fromhex(cleaned)
    return b"\xff" * 6 + mac_bytes * 16
