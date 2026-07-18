"""IP 地址管理引擎（core/ipam.py）。

纯 Python，仅依赖标准库 ipaddress 与 json。不依赖任何 GUI。
对应 gui/ipam_module.py。参考开发文档 §6.x。

数据持久化于 src/netops_studio/data/ipam.json，结构：
    {"subnets": [{"cidr": str, "allocations": [{"ip", "owner", "note", "status"}]}]}
"""

from __future__ import annotations

import ipaddress
import json
import os
from typing import Any, Dict, List, Optional

# data 目录位于包内（core/ 的上一级 → netops_studio/data）
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
DEFAULT_PATH = os.path.join(DATA_DIR, "ipam.json")


def _norm_cidr(cidr: str) -> str:
    """归整 CIDR 为规范网络地址字符串（宽松模式）。"""
    cidr = (cidr or "").strip()
    if not cidr:
        raise ValueError("CIDR 不能为空")
    return str(ipaddress.ip_network(cidr, strict=False))


def _usable(cidr: str) -> int:
    """可用主机数（与 core/subnet.calculate 一致，取 net.hosts() 数量）。"""
    net = ipaddress.ip_network(cidr, strict=False)
    return len(list(net.hosts()))


class IpamStore:
    """IPAM 持久化存储。"""

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = path
        self.data: Dict[str, Any] = {"subnets": []}
        self.load()

    # ---- 持久化 ----
    def load(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and isinstance(loaded.get("subnets"), list):
                    self.data = loaded
                else:
                    self.data = {"subnets": []}
            except (json.JSONDecodeError, OSError, ValueError):
                self.data = {"subnets": []}
        else:
            self.data = {"subnets": []}

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---- 内部查询 ----
    def _find(self, cidr: str) -> Optional[Dict[str, Any]]:
        target = ipaddress.ip_network(cidr, strict=False)
        for sub in self.data["subnets"]:
            if ipaddress.ip_network(sub["cidr"], strict=False) == target:
                return sub
        return None

    def has_subnet(self, cidr: str) -> bool:
        return self._find(cidr) is not None

    # ---- 子网管理 ----
    def add_subnet(self, cidr: str) -> Dict[str, Any]:
        if self._find(cidr) is not None:
            raise ValueError(f"子网已存在：{cidr}")
        sub = {"cidr": _norm_cidr(cidr), "allocations": []}
        self.data["subnets"].append(sub)
        self.save()
        return sub

    def remove_subnet(self, cidr: str) -> None:
        sub = self._find(cidr)
        if sub is None:
            raise ValueError(f"子网不存在：{cidr}")
        self.data["subnets"].remove(sub)
        self.save()


# ---- 纯函数（操作 IpamStore）----

def allocate(store: IpamStore, cidr: str, owner: str, note: str = "") -> str:
    """为指定子网分配一个空闲 IP，返回分配的地址字符串。

    纯函数地查找未占用地址（不依赖外部状态），随后写入存储。
    """
    sub = store._find(cidr)
    if sub is None:
        raise ValueError(f"子网不存在：{cidr}")
    net = ipaddress.ip_network(sub["cidr"], strict=False)
    used = {a.get("ip") for a in sub["allocations"]}
    for host in net.hosts():
        ip = str(host)
        if ip not in used:
            sub["allocations"].append({
                "ip": ip,
                "owner": owner or "",
                "note": note or "",
                "status": "offline",
            })
            store.save()
            return ip
    raise ValueError(f"子网 {cidr} 已无空闲地址")


def release(store: IpamStore, cidr: str, ip: str) -> None:
    """释放子网中某个已分配的 IP。"""
    sub = store._find(cidr)
    if sub is None:
        raise ValueError(f"子网不存在：{cidr}")
    ip = (ip or "").strip()
    for a in sub["allocations"]:
        if a.get("ip") == ip:
            sub["allocations"].remove(a)
            store.save()
            return
    raise ValueError(f"该子网未分配 IP：{ip}")


def utilization(cidr: str, store: IpamStore) -> float:
    """返回子网的已用百分比（0.0 - 100.0）。纯函数。"""
    sub = store._find(cidr)
    if sub is None:
        raise ValueError(f"子网不存在：{cidr}")
    usable = _usable(sub["cidr"])
    if usable <= 0:
        return 0.0
    used = len(sub["allocations"])
    return round(used / usable * 100.0, 4)


def detect_conflicts(store: IpamStore, discovered_hosts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """检测已分配但与发现结果不符的冲突。

    discovered_hosts 元素形如 {"ip": str, "mac": str, "status": str, ...}。
    冲突类型：
      - absent_in_discovery：已分配 IP 在发现结果中不存在（可能被误配/已下线）。
      - status_mismatch：发现端报告的状态与已记录状态不符。
      - mac_mismatch：发现端报告的 MAC 与已记录 MAC 不符（记录 mac 可选）。
    返回冲突列表，每项含 cidr/ip/owner/reason 等字段。纯函数。
    """
    discovered = {h.get("ip"): h for h in discovered_hosts if h.get("ip")}
    conflicts: List[Dict[str, Any]] = []
    for sub in store.data["subnets"]:
        for a in sub["allocations"]:
            ip = a.get("ip")
            dh = discovered.get(ip)
            if dh is None:
                conflicts.append({
                    "cidr": sub["cidr"], "ip": ip,
                    "owner": a.get("owner", ""),
                    "reason": "absent_in_discovery",
                })
                continue
            # 状态不符：我方记为在线，但发现端报告 down/offline 才算异常冲突。
            # （我方 offline、发现 online 属于尚未对账，交由 reconcile 处理，不算冲突）
            dstatus = dh.get("status")
            astatus = a.get("status")
            if astatus == "online" and dstatus in ("down", "offline"):
                conflicts.append({
                    "cidr": sub["cidr"], "ip": ip,
                    "owner": a.get("owner", ""),
                    "reason": "status_mismatch",
                    "allocated_status": astatus, "discovered_status": dstatus,
                })
            dmac = dh.get("mac")
            amac = a.get("mac")
            if dmac and amac and dmac != amac:
                conflicts.append({
                    "cidr": sub["cidr"], "ip": ip,
                    "owner": a.get("owner", ""),
                    "reason": "mac_mismatch",
                    "allocated_mac": amac, "discovered_mac": dmac,
                })
    return conflicts


def reconcile(store: IpamStore, discovered_hosts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据发现结果标记分配项的在线/离线状态。

    返回汇总：{"changes": [...], "online": int, "offline": int, "total": int}。
    会写回存储（save）。纯函数式处理（无外部 IO 依赖，save 除外）。
    """
    discovered = {h.get("ip"): h for h in discovered_hosts if h.get("ip")}
    changes: List[Dict[str, Any]] = []
    for sub in store.data["subnets"]:
        for a in sub["allocations"]:
            ip = a.get("ip")
            dh = discovered.get(ip)
            if dh is None:
                new_status = "offline"
            elif dh.get("status") in ("down", "offline"):
                new_status = "offline"
            else:
                new_status = "online"
            old = a.get("status")
            if old != new_status:
                changes.append({
                    "cidr": sub["cidr"], "ip": ip,
                    "old": old, "new": new_status,
                })
                a["status"] = new_status
    store.save()
    total = sum(len(s["allocations"]) for s in store.data["subnets"])
    online = sum(1 for s in store.data["subnets"] for a in s["allocations"]
                 if a.get("status") == "online")
    return {
        "changes": changes,
        "online": online,
        "offline": total - online,
        "total": total,
    }
