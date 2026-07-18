"""集成与 API 引擎（core/integration.py）。

纯 Python，禁止 import PySide6。重依赖（fastapi / uvicorn / requests）
全部在**函数内惰性 import**，保证本模块可脱离 GUI 单测、可未来 Web 复用。

职责：
1. 本地 API：build_app() 暴露 /health、/subnet/calculate、/discovery/scan、
   /speedtest/external，复用 core 引擎；start_api/stop_api 在后台线程跑 uvicorn。
2. CSV/JSON 转换（纯函数）：devices_to_csv / csv_to_devices / devices_to_json /
   json_to_devices。devices 为 core/discovery.Host 列表（或等价 dict）。
3. 外部系统桩：ZabbixClient / PrometheusClient / NetBoxClient（requests 惰性）。

参考开发文档 §6.3。
"""

from __future__ import annotations

import csv
import io
import json
import threading
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from .discovery import Host, scan_network
from .speedtest import ExternalTester
from .subnet import calculate

# 设备字段顺序（CSV 表头 / JSON 键顺序）
HOST_FIELDS = ("ip", "hostname", "mac", "vendor", "state", "latency_ms")


# ==========================================================================
# 1. 本地 API（FastAPI / uvicorn 惰性）
# ==========================================================================
def build_app():
    """构建 FastAPI 应用，复用 core 引擎。fastapi / pydantic 在此惰性 import。"""
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="NetOps Studio API", version="1.0")

    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok"}

    @app.post("/subnet/calculate")
    def subnet_calculate(req: dict = Body(...)) -> Dict[str, Any]:
        try:
            return asdict(calculate(str(req.get("cidr", ""))))
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc))

    @app.post("/discovery/scan")
    def discovery_scan(req: dict = Body(...)) -> List[Dict[str, Any]]:
        try:
            cidr = str(req.get("cidr", ""))
            workers = int(req.get("workers", 64))
            timeout = int(req.get("timeout", 1))
            hosts = scan_network(cidr, workers=workers, timeout=timeout)
            return [asdict(h) for h in hosts]
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc))

    @app.get("/speedtest/external")
    def speedtest_external() -> Dict[str, Any]:
        try:
            return asdict(ExternalTester().measure())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=str(exc))

    return app


# ---- 后台线程的服务状态（模块级，支撑 start/stop/is_running）----
_API_STATE: Dict[str, Any] = {"server": None, "thread": None, "host": None, "port": None}


def start_api(host: str = "127.0.0.1", port: int = 8000) -> Dict[str, Any]:
    """在后台线程启动 uvicorn 服务（uvicorn.Server.run 不安装信号，可安全入线程）。

    Returns:
        {"host", "port", "url"} 便于 GUI 显示。
    Raises:
        RuntimeError: 已有一个实例在运行。
    """
    if _API_STATE["server"] is not None:
        raise RuntimeError("API 服务已在运行，请先停止")

    import uvicorn

    app = build_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    _API_STATE["server"] = server
    _API_STATE["thread"] = thread
    _API_STATE["host"] = host
    _API_STATE["port"] = port
    return {"host": host, "port": port, "url": f"http://{host}:{port}"}


def stop_api() -> bool:
    """请求后台 uvicorn 退出并等待线程结束。

    Returns:
        True 表示确有运行中的服务被停止；False 表示本来就没有运行。
    """
    server = _API_STATE["server"]
    if server is None:
        return False
    server.should_exit = True
    thread = _API_STATE["thread"]
    if thread is not None:
        thread.join(timeout=10)
    _API_STATE["server"] = None
    _API_STATE["thread"] = None
    _API_STATE["host"] = None
    _API_STATE["port"] = None
    return True


def is_api_running() -> bool:
    """当前是否有运行中的 API 服务。"""
    server = _API_STATE["server"]
    return server is not None and not getattr(server, "should_exit", False)


# ==========================================================================
# 2. CSV / JSON 转换（纯函数，不依赖 fastapi / 网络）
# ==========================================================================
def _device_to_dict(d: Any) -> Dict[str, Any]:
    """统一把 Host / dict 转成字段字典。"""
    if isinstance(d, dict):
        return {k: d.get(k, "") for k in HOST_FIELDS}
    return {k: getattr(d, k, "") for k in HOST_FIELDS}


def _dict_to_host(d: Dict[str, Any]) -> Host:
    """把字段字典还原为 Host（延迟/缺省做容错）。"""
    lat = d.get("latency_ms")
    if lat in ("", None):
        lat = None
    elif isinstance(lat, str):
        try:
            lat = float(lat)
        except ValueError:
            lat = None
    return Host(
        ip=str(d.get("ip", "")),
        hostname=str(d.get("hostname", "")),
        mac=str(d.get("mac", "")),
        vendor=str(d.get("vendor", "")),
        state=str(d.get("state", "up") or "up"),
        latency_ms=lat,
    )


def devices_to_csv(devices: List[Any]) -> str:
    """设备列表 -> CSV 文本（含表头）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(list(HOST_FIELDS))
    for d in devices:
        row = _device_to_dict(d)
        lat = row["latency_ms"]
        writer.writerow([
            row["ip"], row["hostname"], row["mac"], row["vendor"],
            row["state"], "" if lat is None else lat,
        ])
    return buf.getvalue()


def csv_to_devices(text: str) -> List[Host]:
    """CSV 文本 -> Host 列表。表头缺失时回退到 HOST_FIELDS 顺序。"""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return []
    out: List[Host] = []
    for row in reader:
        item = {k: row.get(k, "") for k in HOST_FIELDS}
        out.append(_dict_to_host(item))
    return out


def devices_to_json(devices: List[Any]) -> str:
    """设备列表 -> JSON 文本（ensure_ascii=False 保留中文）。"""
    return json.dumps(
        [_device_to_dict(d) for d in devices],
        ensure_ascii=False, indent=2,
    )


def json_to_devices(text: str) -> List[Host]:
    """JSON 文本 -> Host 列表。期望为对象数组。"""
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON 应为设备对象数组")
    return [_dict_to_host(item) for item in data]


# ==========================================================================
# 3. 外部系统桩（requests 惰性）
# ==========================================================================
class ZabbixClient:
    """Zabbix API 客户端桩。缺失/错误均抛清晰信息。"""

    def __init__(self, url: str, user: str, token: str) -> None:
        self.url = (url or "").rstrip("/")
        self.user = user or ""
        self.token = token or ""

    def get_hosts(self) -> List[Dict[str, Any]]:
        if not self.url:
            raise ValueError("Zabbix 配置缺失：url 必填")
        if not self.token:
            raise ValueError("Zabbix 配置缺失：token 必填")
        import requests

        try:
            resp = requests.post(
                self.url + "/api_jsonrpc.php",
                json={
                    "jsonrpc": "2.0", "method": "host.get",
                    "params": {"output": ["host", "name", "status"]},
                    "id": 1, "auth": self.token,
                },
                headers={"Content-Type": "application/json-rpc"},
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Zabbix 连接失败：{exc}")
        if "error" in payload:
            raise RuntimeError(f"Zabbix API 错误：{payload['error']}")
        return payload.get("result", [])


class PrometheusClient:
    """Prometheus HTTP API 客户端桩。"""

    def __init__(self, url: str) -> None:
        self.url = (url or "").rstrip("/")

    def get_hosts(self) -> List[Dict[str, Any]]:
        if not self.url:
            raise ValueError("Prometheus 配置缺失：url 必填")
        import requests

        try:
            resp = requests.get(self.url + "/api/v1/targets", timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Prometheus 连接失败：{exc}")
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus 返回非 success：{payload.get('error', '未知错误')}")
        return payload.get("data", {}).get("activeTargets", [])


class NetBoxClient:
    """NetBox REST API 客户端桩。"""

    def __init__(self, url: str, token: str) -> None:
        self.url = (url or "").rstrip("/")
        self.token = token or ""

    def get_hosts(self) -> List[Dict[str, Any]]:
        if not self.url:
            raise ValueError("NetBox 配置缺失：url 必填")
        if not self.token:
            raise ValueError("NetBox 配置缺失：token 必填")
        import requests

        try:
            resp = requests.get(
                self.url + "/api/dcim/devices/?limit=50",
                headers={"Authorization": f"Token {self.token}"},
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"NetBox 连接失败：{exc}")
        return payload.get("results", [])
