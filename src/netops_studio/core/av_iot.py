"""音视频物联引擎（core/av_iot.py）。

ONVIF 发现（WS-Discovery 多播）、GetDeviceInformation、SIP/VoIP 语音质量
（简化 E-model）、RTSP 流探测（SDP 解析）。本层禁止 import PySide6；
重依赖 requests 在函数内惰性 import。参考开发文档 §6.x。
"""

from __future__ import annotations

import math
import socket
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional

# WS-Discovery / ONVIF 命名空间
_NS_WSD = "http://schemas.xmlsoap.org/ws/2005/04/discovery"
_NS_WSA = "http://schemas.xmlsoap.org/ws/2004/08/addressing"
_NS_SOAP = "http://www.w3.org/2003/05/soap-envelope"
_NS_TDS = "http://www.onvif.org/ver10/device/wsdl"

_MULTICAST_GROUP = "239.255.255.250"
_DISCOVERY_PORT = 3702


def _local(tag: str) -> str:
    """提取 XML 标签的本地名（去掉 {namespace} 前缀）。"""
    return tag.split("}", 1)[-1] if "}" in tag else tag


# --------------------------------------------------------------------------
# ONVIF 发现（WS-Discovery）
# --------------------------------------------------------------------------
def build_probe() -> str:
    """构造 WS-Discovery Probe 多播 SOAP 报文（发给 239.255.255.250:3702）。"""
    msg_id = uuid.uuid4().urn  # urn:uuid:xxxx
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">\n'
        "  <soap:Header>\n"
        f'    <wsa:MessageID>{msg_id}</wsa:MessageID>\n'
        '    <wsa:To soap:mustUnderstand="1">'
        "urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>\n"
        '    <wsa:Action soap:mustUnderstand="1">'
        "http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>\n"
        "  </soap:Header>\n"
        "  <soap:Body>\n"
        '    <wsd:Probe>\n'
        "      <wsd:Types>wsd:NetworkVideoTransmitter</wsd:Types>\n"
        "    </wsd:Probe>\n"
        "  </soap:Body>\n"
        "</soap:Envelope>\n"
    )


@dataclass
class OnvifDevice:
    endpoint: str = ""                 # EndpointReference / Address (urn:uuid:...)
    types: str = ""                    # 设备类型
    scopes: List[str] = field(default_factory=list)
    xaddrs: List[str] = field(default_factory=list)   # 可访问的服务地址
    metadata_version: str = ""


def parse_probe(xml_text: str) -> List[OnvifDevice]:
    """纯解析函数：从 WS-Discovery ProbeMatch 应答 XML 中解析设备列表。"""
    devices: List[OnvifDevice] = []
    if not xml_text or not xml_text.strip():
        return devices
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return devices

    for elem in root.iter():
        if _local(elem.tag) != "ProbeMatch":
            continue
        dev = OnvifDevice()

        # EndpointReference/Address
        for child in elem.iter():
            if _local(child.tag) == "Address":
                dev.endpoint = (child.text or "").strip()
                break

        for child in elem:
            ln = _local(child.tag)
            if ln == "Types":
                dev.types = (child.text or "").strip()
            elif ln == "Scopes":
                dev.scopes = (child.text or "").strip().split()
            elif ln == "XAddrs":
                dev.xaddrs = (child.text or "").strip().split()
            elif ln == "MetadataVersion":
                dev.metadata_version = (child.text or "").strip()
        devices.append(dev)
    return devices


def discover_onvif(
    timeout: float = 3.0,
    multicast_group: str = _MULTICAST_GROUP,
    port: int = _DISCOVERY_PORT,
    bind_interface: str = "",
) -> List[OnvifDevice]:
    """发送 WS-Discovery Probe 并收集应答，返回发现的 ONVIF 设备。

    使用 UDP 多播套接字；无应答时返回空列表（不会抛错，便于离线环境）。
    """
    msg = build_probe().encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    if bind_interface:
        try:
            sock.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                socket.inet_aton(bind_interface),
            )
        except OSError:
            pass
    sock.settimeout(timeout)
    try:
        try:
            sock.sendto(msg, (multicast_group, port))
        except OSError:
            return []

        devices: List[OnvifDevice] = []
        seen = set()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                break
            text = data.decode("utf-8", "replace")
            try:
                for d in parse_probe(text):
                    if d.endpoint and d.endpoint not in seen:
                        seen.add(d.endpoint)
                        devices.append(d)
            except Exception:  # noqa: BLE001
                continue
        return devices
    finally:
        sock.close()


# --------------------------------------------------------------------------
# GetDeviceInformation（ONVIF，HTTP/SOAP，惰性 import requests）
# --------------------------------------------------------------------------
@dataclass
class DeviceInformation:
    manufacturer: str = ""
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    hardware_id: str = ""


def get_device_information(
    xaddr: str,
    timeout: int = 5,
    user: str = "",
    pwd: str = "",
) -> DeviceInformation:
    """调用 ONVIF 设备服务的 GetDeviceInformation。

    通过 HTTP POST SOAP 实现；requests 为惰性依赖。缺失时抛出清晰错误。
    """
    try:
        import requests
    except ImportError as exc:  # 重依赖缺失时给出明确提示
        raise RuntimeError(
            "缺少 requests 依赖，无法调用 ONVIF 服务，请先 `pip install requests`"
        ) from exc

    msg_id = uuid.uuid4().urn
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:tds="http://www.onvif.org/ver10/device/wsdl">\n'
        "  <soap:Header>\n"
        f"    <wsa:MessageID>{msg_id}</wsa:MessageID>\n"
        f"    <wsa:To>{xaddr}</wsa:To>\n"
        "    <wsa:Action>"
        "http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation</wsa:Action>\n"
        "  </soap:Header>\n"
        "  <soap:Body>\n"
        "    <tds:GetDeviceInformation/>\n"
        "  </soap:Body>\n"
        "</soap:Envelope>\n"
    )

    headers = {
        "Content-Type": 'application/soap+xml; charset=utf-8',
        "SOAPAction": (
            '"http://www.onvif.org/ver10/device/wsdl/GetDeviceInformation"'
        ),
    }
    try:
        resp = requests.post(xaddr, data=body.encode("utf-8"),
                             headers=headers, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"调用 ONVIF 服务失败（{xaddr}）：{exc}") from exc

    info = DeviceInformation()
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise RuntimeError(f"ONVIF 服务返回非 XML：{exc}") from exc

    fields = {
        "Manufacturer": "manufacturer",
        "Model": "model",
        "FirmwareVersion": "firmware_version",
        "SerialNumber": "serial_number",
        "HardwareId": "hardware_id",
    }
    for elem in root.iter():
        name = _local(elem.tag)
        if name in fields and elem.text:
            setattr(info, fields[name], elem.text.strip())
    return info


# --------------------------------------------------------------------------
# SIP / VoIP 语音质量（简化 E-model）
# --------------------------------------------------------------------------
def estimate_mos(loss_percent: float, jitter_ms: float, codec_ie: float = 0.0) -> float:
    """基于简化 E-model 估算 MOS（Mean Opinion Score，1~4.5）。

    Args:
        loss_percent: 丢包率（%）
        jitter_ms: 抖动（毫秒），作为延迟损伤代理
        codec_ie: 编解码器基础损伤（默认 0，近似 G.711）

    Returns:
        估算的 MOS 值（float，约 1.0 ~ 4.5）
    """
    loss_percent = max(0.0, float(loss_percent))
    jitter_ms = max(0.0, float(jitter_ms))
    codec_ie = max(0.0, float(codec_ie))

    r0 = 93.2                      # 基础信号质量
    i_loss = 95.0 * (1.0 - math.exp(-loss_percent / 15.0))   # 丢包损伤
    i_jit = 0.024 * jitter_ms + 0.11 * max(0.0, jitter_ms - 177.3)  # 抖动/延迟损伤
    r = r0 - i_loss - i_jit - codec_ie
    r = max(0.0, min(100.0, r))

    # R 值 -> MOS 标准转换公式
    mos = 1.0 + 0.035 * r + r * (r - 60.0) * (100.0 - r) * 7e-6
    return round(mos, 2)


# --------------------------------------------------------------------------
# RTSP 流探测（SDP 解析）
# --------------------------------------------------------------------------
@dataclass
class SdpTrack:
    media: str = ""          # video / audio
    port: int = 0
    proto: str = ""          # RTP/AVP 等
    payload_type: str = ""   # 动态/静态负载类型
    codec: str = ""          # H264 / PCMU ...
    clock_rate: int = 0      # 时钟频率 Hz
    control: str = ""        # a=control: 轨道标识


def parse_sdp(sdp_text: str) -> List[SdpTrack]:
    """纯解析函数：从 SDP 文本中解析媒体轨道列表。"""
    tracks: List[SdpTrack] = []
    current: Optional[SdpTrack] = None

    for raw in sdp_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("m="):
            parts = line[2:].split()
            if len(parts) >= 4:
                try:
                    port = int(parts[1])
                except ValueError:
                    port = 0
                current = SdpTrack(
                    media=parts[0],
                    port=port,
                    proto=parts[2],
                    payload_type=parts[3],
                )
                tracks.append(current)
        elif line.startswith("a=") and current is not None:
            attr = line[2:]
            if attr.startswith("rtpmap:"):
                rest = attr[len("rtpmap:"):].strip()
                sp = rest.split(None, 1)
                if len(sp) == 2 and sp[0] == current.payload_type:
                    codec_clk = sp[1]
                    if "/" in codec_clk:
                        codec, clk = codec_clk.split("/", 1)
                        current.codec = codec
                        try:
                            current.clock_rate = int(clk)
                        except ValueError:
                            current.clock_rate = 0
            elif attr.startswith("control:"):
                current.control = attr[len("control:"):]
    return tracks


def describe_stream(
    url: str,
    timeout: int = 5,
    user: str = "",
    pwd: str = "",
) -> dict:
    """探测 RTSP 流描述（SDP）。

    HTTP(S) URL 使用 requests（惰性依赖）直接抓取；
    rtsp:// 通过原生套接字发送 RTSP DESCRIBE 请求。
    返回 {"url", "sdp", "tracks"}。
    """
    if url.lower().startswith(("http://", "https://")):
        try:
            import requests
        except ImportError as exc:
            raise RuntimeError(
                "缺少 requests 依赖，无法获取流描述，请先 `pip install requests`"
            ) from exc
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            sdp = resp.text
        except requests.RequestException as exc:
            raise RuntimeError(f"获取流描述失败（{url}）：{exc}") from exc
    else:
        sdp = _rtsp_describe(url, timeout=timeout, user=user, pwd=pwd)

    return {"url": url, "sdp": sdp, "tracks": parse_sdp(sdp)}


def _rtsp_describe(url: str, timeout: int = 5, user: str = "", pwd: str = "") -> str:
    """通过原生套接字发送 RTSP DESCRIBE 并返回 SDP 正文。"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 554

    try:
        sock = socket.create_connection((host, port), timeout=timeout)
    except OSError as exc:
        raise RuntimeError(f"无法连接 RTSP 服务（{host}:{port}）：{exc}") from exc

    try:
        req = (
            f"DESCRIBE {url} RTSP/1.0\r\n"
            "CSeq: 1\r\n"
            "Accept: application/sdp\r\n"
            "User-Agent: NetOpsStudio/1.0\r\n"
        )
        if user:
            import base64

            token = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            req += f"Authorization: Basic {token}\r\n"
        req += "\r\n"
        sock.sendall(req.encode("utf-8"))

        data = b""
        while b"\r\n\r\n" not in data:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        header, _, body = data.partition(b"\r\n\r\n")

        content_length = 0
        for hline in header.decode("utf-8", "replace").split("\r\n"):
            if hline.lower().startswith("content-length:"):
                try:
                    content_length = int(hline.split(":", 1)[1].strip())
                except ValueError:
                    content_length = 0
        while content_length and len(body) < content_length:
            chunk = sock.recv(4096)
            if not chunk:
                break
            body += chunk
        return body.decode("utf-8", "replace")
    finally:
        sock.close()
