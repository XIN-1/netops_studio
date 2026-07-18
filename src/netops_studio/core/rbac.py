"""平台与权限引擎（core/rbac.py）。

涵盖：RBAC 鉴权、审计日志持久化、插件扫描、命令面板动作注册表、仪表盘配置。
纯 Python 引擎层：禁止 import PySide6 / 任何 GUI 依赖，仅标准库（json、os）。
返回 dataclass / dict / list 结构化结果，由 gui 渲染。

参考文档 §7 / §9。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "..", "data")
AUDIT_PATH = os.path.join(DATA_DIR, "audit.json")
DASHBOARD_PATH = os.path.join(DATA_DIR, "dashboard.json")
PLUGINS_DIR = os.path.join(DATA_DIR, "plugins")

# --------------------------------------------------------------------------
# RBAC 角色与权限定义
# --------------------------------------------------------------------------
# "*" 表示拥有全部权限。action 采用 "资源.操作" 命名（如 discovery.run）。
ROLES: Dict[str, List[str]] = {
    "admin": ["*"],
    "operator": [
        "discovery.run", "discovery.view",
        "diagnostics.run", "diagnostics.view",
        "speedtest.run", "speedtest.view",
        "subnet.compute", "subnet.view",
        "codec.use", "codec.view",
        "monitor.poll", "monitor.view",
        "config.backup", "config.push", "config.view",
        "audit.view", "dashboard.view", "dashboard.configure",
        "plugin.scan", "plugin.view",
    ],
    "viewer": [
        "discovery.view", "diagnostics.view", "speedtest.view",
        "subnet.view", "codec.view", "monitor.view",
        "config.view", "audit.view", "dashboard.view", "plugin.view",
    ],
}


@dataclass
class User:
    name: str
    role: str


def check_permission(role: str, action: str) -> bool:
    """纯函数：判定 role 是否拥有 action 权限。

    "*" 表示全部权限；未知角色（不在 ROLES 中）一律拒绝。
    """
    perms = ROLES.get(role)
    if perms is None:
        return False
    return "*" in perms or action in perms


# --------------------------------------------------------------------------
# 审计日志（持久化 data/audit.json）
# --------------------------------------------------------------------------
def _now_iso() -> str:
    """当前时间的 ISO 字符串（秒精度），用于审计条目的时间戳。"""
    return datetime.now().isoformat(timespec="seconds")


class AuditLog:
    """审计日志：追加写 data/audit.json，支持加载与按关键字查询。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or AUDIT_PATH
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def record(self, user, action: str, detail: str = "") -> dict:
        """记录一条审计。user 可为 User 或 字符串。返回该条记录 dict。"""
        if isinstance(user, User):
            name, role = user.name, user.role
        else:
            name, role = str(user), ""
        entry = {
            "ts": _now_iso(),
            "user": name,
            "role": role,
            "action": action,
            "detail": detail,
        }
        logs = self.load()
        logs.append(entry)
        self._write(logs)
        return entry

    def load(self) -> List[dict]:
        """读取审计日志列表；文件缺失或内容损坏时返回空列表（绝不抛错）。"""
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def search(self, query: str = "") -> List[dict]:
        """查询审计日志。query 为空返回全部；否则匹配 user/role/action/detail。"""
        logs = self.load()
        q = (query or "").strip().lower()
        if not q:
            return logs
        out: List[dict] = []
        for e in logs:
            hay = " ".join(
                str(e.get(k, "")) for k in ("user", "role", "action", "detail")
            ).lower()
            if q in hay:
                out.append(e)
        return out

    def _write(self, logs: List[dict]) -> None:
        """将审计列表整体写回 JSON 文件（覆盖式）。"""
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# 插件扫描（读取 data/plugins/<id>/metadata.json）
# --------------------------------------------------------------------------
def scan_plugins(dir: Optional[str] = None) -> List[dict]:
    """扫描插件目录，返回各插件 metadata（dict）列表。"""
    plugins_dir = dir or PLUGINS_DIR
    if not os.path.isdir(plugins_dir):
        return []
    result: List[dict] = []
    for name in sorted(os.listdir(plugins_dir)):
        meta_path = os.path.join(plugins_dir, name, "metadata.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(meta, dict):
            continue
        meta.setdefault("id", name)
        result.append(meta)
    return result


def ensure_sample_plugins(dir: Optional[str] = None) -> List[str]:
    """建示例插件占位目录 + metadata.json（幂等）。返回创建的插件 id 列表。"""
    plugins_dir = dir or PLUGINS_DIR
    os.makedirs(plugins_dir, exist_ok=True)
    samples = [
        {
            "id": "hello_alert",
            "name": "示例：告警桌面通知",
            "version": "1.0.0",
            "description": "演示插件：触发器产生告警时弹出桌面通知。",
            "author": "NetOps Studio",
        },
        {
            "id": "netbox_sync",
            "name": "示例：NetBox 资产同步",
            "version": "0.9.0",
            "description": "演示插件：将发现到的资产批量同步至 NetBox IPAM。",
            "author": "NetOps Studio",
        },
    ]
    created: List[str] = []
    for meta in samples:
        pdir = os.path.join(plugins_dir, meta["id"])
        os.makedirs(pdir, exist_ok=True)
        mpath = os.path.join(pdir, "metadata.json")
        if not os.path.isfile(mpath):
            with open(mpath, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        created.append(meta["id"])
    return created


# --------------------------------------------------------------------------
# 命令面板：ACTIONS 注册表 + 搜索
# --------------------------------------------------------------------------
# 注册表：action 名称 -> 描述（用于命令面板搜索，与 rbac.ROLES 的权限点不完全对应）
ACTIONS: Dict[str, str] = {
    "discovery.scan": "扫描网络资产",
    "diagnostics.ping": "Ping 主机",
    "diagnostics.traceroute": "路由追踪",
    "speedtest.start": "开始测速",
    "subnet.compute": "计算子网",
    "codec.encode": "编解码转换",
    "config.backup": "备份设备配置",
    "config.push": "下发配置",
    "monitor.poll": "SNMP 轮询",
    "audit.view": "查看审计日志",
    "dashboard.view": "查看仪表盘",
    "dashboard.configure": "配置仪表盘 KPI",
    "plugin.scan": "扫描插件",
    "theme.toggle": "切换主题",
    "lang.toggle": "切换语言",
    "user.create": "创建用户",
    "role.assign": "分配角色",
}


def search_actions(query: str) -> List[str]:
    """纯函数：按名称或描述模糊匹配 ACTIONS，返回排序后的 action 名称列表。"""
    q = (query or "").strip().lower()
    if not q:
        return sorted(ACTIONS.keys())
    return sorted(
        name for name, desc in ACTIONS.items()
        if q in name.lower() or q in desc.lower()
    )


# --------------------------------------------------------------------------
# 自定义仪表盘：DashboardConfig（保存哪些 KPI 显示）
# --------------------------------------------------------------------------
DEFAULT_DASHBOARD: Dict[str, bool] = {
    "online": True,
    "latency": True,
    "throughput": True,
    "alerts": True,
}


class DashboardConfig:
    """自定义仪表盘：各 KPI 是否显示的开关（dict[str, bool]）。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or DASHBOARD_PATH

    def load(self) -> Dict[str, bool]:
        if not os.path.isfile(self.path):
            return dict(DEFAULT_DASHBOARD)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return dict(DEFAULT_DASHBOARD)
        if not isinstance(data, dict):
            return dict(DEFAULT_DASHBOARD)
        merged = dict(DEFAULT_DASHBOARD)
        merged.update({k: bool(v) for k, v in data.items()})
        return merged

    def save(self, config: Dict[str, bool]) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
