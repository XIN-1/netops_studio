"""子网计算引擎（core/subnet.py）。

纯 Python，仅依赖标准库 ipaddress。不依赖任何 GUI。
参考开发文档 §6.1。
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import List


@dataclass
class SubnetResult:
    """单个 CIDR 的计算结果。"""

    network: str
    broadcast: str
    netmask: str
    wildcard: str
    prefixlen: int
    host_count: int
    first_host: str | None
    last_host: str | None
    usable: int
    version: int = 4


def calculate(cidr: str) -> SubnetResult:
    """计算给定 CIDR 的子网信息。

    Args:
        cidr: 形如 "192.168.1.0/24" 或 "10.0.0.5/8"（宽松模式，自动归整）。

    Returns:
        SubnetResult
    """
    cidr = (cidr or "").strip()
    if not cidr:
        raise ValueError("CIDR 不能为空")
    net = ipaddress.ip_network(cidr, strict=False)
    hosts = list(net.hosts())
    return SubnetResult(
        network=str(net.network_address),
        broadcast=str(net.broadcast_address) if net.version == 4 else "N/A",
        netmask=str(net.netmask),
        wildcard=str(net.hostmask),
        prefixlen=net.prefixlen,
        host_count=int(net.num_addresses),
        first_host=str(hosts[0]) if hosts else None,
        last_host=str(hosts[-1]) if hosts else None,
        usable=max(int(net.num_addresses) - 2, 0),
        version=net.version,
    )


def subnet_split(cidr: str, new_prefix: int) -> List[SubnetResult]:
    """将网络按指定前缀拆分为多个子网。

    Args:
        cidr: 原始网络
        new_prefix: 拆分后的前缀长度（必须 > 原前缀）
    """
    net = ipaddress.ip_network(cidr.strip(), strict=False)
    if new_prefix <= net.prefixlen:
        raise ValueError(f"新前缀 {new_prefix} 必须大于原前缀 {net.prefixlen}")
    return [calculate(str(sub)) for sub in net.subnets(new_prefix=new_prefix)]


def ip_in_network(ip: str, cidr: str) -> bool:
    """判断 IP 是否属于某个网络。"""
    return ipaddress.ip_address(ip.strip()) in ipaddress.ip_network(cidr.strip(), strict=False)


def wildcard_to_mask(wildcard: str) -> str:
    """通配符掩码转子网掩码字符串。"""
    net = ipaddress.ip_network(f"0.0.0.0/{32 - _wildcard_prefix(wildcard)}", strict=False)
    return str(net.netmask)


def _wildcard_prefix(wildcard: str) -> int:
    addr = ipaddress.ip_address(wildcard.strip())
    bits = 0
    for b in addr.packed:
        bits += bin(b).count("1")
    return bits
