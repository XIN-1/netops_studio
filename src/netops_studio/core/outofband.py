"""带外与机房引擎（core/outofband.py）。

涵盖：
  - Redfish（iDRAC /  BMC）机箱遥测：get_chassis（惰性 requests）/ parse_redfish（纯解析）
  - ipmitool 传感器：find_ipmitool（惰性查找）/ get_sensors（惰性 subprocess）/ parse_ipmitool（纯解析）
  - PDU 电源控制：rest / snmp 占位（方法桩 + 清晰降级）
  - 温湿度：parse_env（纯解析）
  - 机架/线缆：RackStore 持久化 data/racks.json

纯 Python 引擎层，禁止 import PySide6 / Qt。重依赖（requests）一律函数内惰性导入；
ipmitool 按需查找、惰性调用。所有解析函数均为纯函数，便于单测。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "..", "data")
RACKS_PATH = os.path.join(DATA_DIR, "racks.json")

# ipmitool 常见安装路径（find_ipmitool 的兜底搜索列表）
_IPMITOOL_CANDIDATES = (
    "ipmitool",
    "/usr/bin/ipmitool",
    "/usr/local/bin/ipmitool",
    "/sbin/ipmitool",
    "/opt/ipmitool/bin/ipmitool",
    "C:\\Program Files\\ipmitool\\ipmitool.exe",
)


# --------------------------------------------------------------------------
# Redfish（iDRAC / BMC）
# --------------------------------------------------------------------------
def get_chassis(url: str, user: str, pwd: str, timeout: int = 10) -> str:
    """通过 Redfish 获取机箱遥测原始 JSON 文本（惰性 requests）。

    自动补全 https 协议与 Chassis 资源路径；自行忽略证书校验（机房内网常见自签）。
    失败时抛出异常，由调用方（AsyncWorker Job）统一降级为错误信号。
    """
    import requests

    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:  # noqa: BLE001
        pass

    if "://" not in url:
        url = "https://" + url
    url = url.rstrip("/")
    if not url.endswith("/Chassis") and "/Chassis/" not in url:
        url = url + "/redfish/v1/Chassis/1"

    resp = requests.get(url, auth=(user, pwd), verify=False, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_redfish(json_text: str) -> Dict[str, object]:
    """纯解析 Redfish Chassis JSON -> {temp, power, health}。

    temp:  {传感器名: 摄氏温度}
    power: {电源域: 瓦特}
    health: 顶层 Status.Health 字符串（缺省 "Unknown"）
    缺失字段一律降级为空字典 / Unknown，绝不抛错。
    """
    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, TypeError):
        return {"temp": {}, "power": {}, "health": "Unknown"}

    def _num(v) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    temp: Dict[str, float] = {}
    thermal = data.get("Thermal") or {}
    for t in thermal.get("Temperatures", []) or []:
        name = t.get("Name") or t.get("Id")
        val = _num(t.get("ReadingCelsius"))
        if name is not None and val is not None:
            temp[name] = val

    power: Dict[str, float] = {}
    pwr = data.get("Power") or {}
    for pc in pwr.get("PowerControl", []) or []:
        name = pc.get("Name") or pc.get("Id") or "Power"
        val = _num(pc.get("PowerConsumedWatts"))
        if val is not None:
            power[name] = val

    status = data.get("Status") or {}
    health = status.get("Health") or "Unknown"

    return {"temp": temp, "power": power, "health": health}


# --------------------------------------------------------------------------
# ipmitool 传感器
# --------------------------------------------------------------------------
def find_ipmitool() -> Optional[str]:
    """惰性查找 ipmitool 可执行文件，返回路径或 None。"""
    for candidate in _IPMITOOL_CANDIDATES:
        if candidate == "ipmitool":
            found = shutil.which("ipmitool")
            if found:
                return found
            continue
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def get_sensors(host: str, user: str, pwd: str, timeout: int = 30) -> str:
    """通过 ipmitool -I lanplus sensor 获取传感器列表，返回原始文本。

    ipmitool 未安装时抛出 RuntimeError 并给出清晰提示（降级由上层处理）。
    """
    tool = find_ipmitool()
    if not tool:
        raise RuntimeError(
            "未找到 ipmitool，请先安装（如 apt install ipmitool / yum install ipmitool）。"
        )
    cmd = [tool, "-H", host, "-U", user, "-P", pwd, "-I", "lanplus", "sensor"]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ipmitool 获取 {host} 传感器超时")
    # 合并 stdout/stderr，便于解析与排错
    raw = (out.stdout or "") + (out.stderr or "")
    if out.returncode != 0 and not raw.strip():
        raise RuntimeError(f"ipmitool 执行失败（退出码 {out.returncode}）")
    return raw


def parse_ipmitool(text: str) -> Dict[str, object]:
    """纯解析 `ipmitool sensor` 输出 -> {sensor: value}。

    经典管道分隔格式：`名称 | 数值 | 单位 | 状态 | ...`
    数值可解析为 float 则存为 float，否则保留原始字符串。
    """
    result: Dict[str, object] = {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        name = parts[0]
        if not name:
            continue
        raw_val = parts[1]
        try:
            value: object = float(raw_val)
        except (TypeError, ValueError):
            value = raw_val
        result[name] = value
    return result


# --------------------------------------------------------------------------
# PDU 电源控制（rest / snmp 占位，清晰降级）
# --------------------------------------------------------------------------
def pdu_control_rest(url: str, outlet: str, action: str, **kwargs) -> Dict[str, object]:
    """PDU REST 控制占位。

    尚未实现；返回清晰降级信息，供 GUI 直接展示，绝不抛未实现异常打断流程。
    """
    return {
        "status": "not_implemented",
        "protocol": "rest",
        "outlet": outlet,
        "action": action,
        "message": (
            "PDU REST 控制接口尚未实现，已降级为只读占位。"
            "后续版本将支持通过 REST 切换智能 PDU 端口供电。"
        ),
    }


def pdu_control_snmp(host: str, outlet: int, action: str, community: str = "private",
                     **kwargs) -> Dict[str, object]:
    """PDU SNMP 控制占位。

    尚未实现；返回清晰降级信息，供 GUI 直接展示。
    """
    return {
        "status": "not_implemented",
        "protocol": "snmp",
        "host": host,
        "outlet": outlet,
        "action": action,
        "community": community,
        "message": (
            "PDU SNMP 控制接口尚未实现，已降级为只读占位。"
            "后续版本将支持通过 SNMP SET 控制 PDU 端口（如 APC 1.3.6.1.4.1.318.x）。"
        ),
    }


# --------------------------------------------------------------------------
# 温湿度解析（纯解析）
# --------------------------------------------------------------------------
def parse_env(text: str) -> Dict[str, float]:
    """纯解析温湿度文本 -> {temp, humidity}（缺省不出现）。

    兼容两种来源：
      1) 标签行：温度/Temp/temperature、湿度/Humidity/RH（支持中文与英文）
      2) ipmitool `sensor` 管道行：依单位判定（degrees C -> 温度，% / RH -> 湿度）
    数值解析失败或缺失则对应键不出现在结果中。
    """
    import re

    temp: Optional[float] = None
    humidity: Optional[float] = None

    def _num(v) -> Optional[float]:
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    for line in text.splitlines():
        low = line.lower()
        # 1) 标签式
        if any(k in low for k in ("温度", "temp", "temperature")) and ":" in line:
            m = re.search(r"([+-]?\d+(?:\.\d+)?)", line)
            if m and temp is None:
                temp = float(m.group(1))
            continue
        if any(k in low for k in ("湿度", "humid", "rh")) and ":" in line:
            m = re.search(r"([+-]?\d+(?:\.\d+)?)", line)
            if m and humidity is None:
                humidity = float(m.group(1))
            continue
        # 2) ipmitool 管道式：name | value | units | status
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                units = parts[2].lower()
                val = _num(parts[1])
                if val is not None:
                    if "c" in units and ("temp" in parts[0].lower() or "度" in parts[2] or "deg" in units):
                        if temp is None:
                            temp = val
                    elif "%" in units or "rh" in units or "humid" in parts[0].lower():
                        if humidity is None:
                            humidity = val

    result: Dict[str, float] = {}
    if temp is not None:
        result["temp"] = temp
    if humidity is not None:
        result["humidity"] = humidity
    return result


# --------------------------------------------------------------------------
# 机架 / 线缆持久化
# --------------------------------------------------------------------------
class RackStore:
    """机架与设备拓扑持久化（data/racks.json）。

    数据结构：[{"name": str, "devices": [{"u": int, "name": str, "sn": str}]}, ...]
    所有写操作立即落盘；可在单测中传入自定义 path 隔离。
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or RACKS_PATH
        self.racks: List[Dict[str, object]] = []
        self.load()

    # -- 持久化 --
    def load(self) -> None:
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.racks = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.racks = []
        else:
            self.racks = []

    def save(self) -> None:
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.racks, f, ensure_ascii=False, indent=2)

    # -- 查询 --
    def get_rack(self, name: str) -> Optional[Dict[str, object]]:
        for r in self.racks:
            if r.get("name") == name:
                return r
        return None

    def list_racks(self) -> List[str]:
        return [r.get("name", "") for r in self.racks]

    # -- 写：机架 --
    def add_rack(self, name: str) -> bool:
        """新增机架；已存在则忽略（返回 False）。"""
        if self.get_rack(name) is not None:
            return False
        self.racks.append({"name": name, "devices": []})
        self.save()
        return True

    def remove_rack(self, name: str) -> bool:
        """删除机架及其设备；不存在返回 False。"""
        before = len(self.racks)
        self.racks = [r for r in self.racks if r.get("name") != name]
        changed = len(self.racks) != before
        if changed:
            self.save()
        return changed

    # -- 写：设备 --
    def add_device(self, rack: str, u: int, name: str, sn: str = "") -> bool:
        """向指定机架 U 位添加设备；机架不存在返回 False。"""
        r = self.get_rack(rack)
        if r is None:
            return False
        devices = r.setdefault("devices", [])
        devices.append({"u": int(u), "name": name, "sn": sn})
        self.save()
        return True

    def remove_device(self, rack: str, name: str) -> bool:
        """从机架移除指定名称设备；不存在返回 False。"""
        r = self.get_rack(rack)
        if r is None:
            return False
        devices = r.get("devices", [])
        before = len(devices)
        r["devices"] = [d for d in devices if d.get("name") != name]
        changed = len(r["devices"]) != before
        if changed:
            self.save()
        return changed
