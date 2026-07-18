"""编解码工具引擎（core/codec.py）。

纯计算，无外部依赖，桌面端优先落地。参考开发文档 §6.6。
支持：Base64 / URL / 进制互转 / 哈希 / JWT 解析 / 时间戳转换 / PEM 证书解析。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# --------------------------------------------------------------------------
# Base64 / URL
# --------------------------------------------------------------------------
def base64_encode(text: str, urlsafe: bool = False) -> str:
    data = text.encode("utf-8")
    return base64.urlsafe_b64encode(data).decode() if urlsafe else base64.b64encode(data).decode()


def base64_decode(data: str, urlsafe: bool = False) -> str:
    raw = data.strip()
    # 补齐 '=' 填充
    missing = (-len(raw)) % 4
    raw += "=" * missing
    try:
        decoded = base64.urlsafe_b64decode(raw) if urlsafe else base64.b64decode(raw)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Base64 解码失败：{exc}")
    return decoded.decode("utf-8", errors="replace")


def url_encode(text: str) -> str:
    return urllib.parse.quote(text, safe="")


def url_decode(data: str) -> str:
    return urllib.parse.unquote(data)


# --------------------------------------------------------------------------
# 进制互转
# --------------------------------------------------------------------------
def convert_base(value: str, src_base: int, dst_base: int) -> str:
    """在 2/8/10/16 进制间互转。"""
    if src_base not in (2, 8, 10, 16) or dst_base not in (2, 8, 10, 16):
        raise ValueError("仅支持 2/8/10/16 进制")
    try:
        num = int(value.strip(), src_base)
    except ValueError as exc:
        raise ValueError(f"输入不是合法的 {src_base} 进制数：{exc}")
    if dst_base == 2:
        return bin(num)[2:]
    if dst_base == 8:
        return oct(num)[2:]
    if dst_base == 16:
        return hex(num)[2:].upper()
    return str(num)


# --------------------------------------------------------------------------
# 哈希
# --------------------------------------------------------------------------
def hash_data(text: str, algo: str = "sha256") -> str:
    algo = algo.lower()
    if algo == "crc32":
        return format(binascii.crc32(text.encode("utf-8")) & 0xFFFFFFFF, "08x")
    h = hashlib.new(algo)
    h.update(text.encode("utf-8"))
    return h.hexdigest()


# --------------------------------------------------------------------------
# JWT 解析
# --------------------------------------------------------------------------
@dataclass
class JwtParts:
    header: dict
    payload: dict
    signature: str
    valid_b64: bool


def jwt_parse(token: str) -> JwtParts:
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise ValueError("JWT 应包含 3 段（header.payload.signature）")
    header = _b64url_json(parts[0])
    payload = _b64url_json(parts[1])
    return JwtParts(header=header, payload=payload, signature=parts[2], valid_b64=True)


def _b64url_json(seg: str) -> dict:
    seg += "=" * ((-len(seg)) % 4)
    raw = base64.urlsafe_b64decode(seg)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败：{exc}")


# --------------------------------------------------------------------------
# 时间戳转换
# --------------------------------------------------------------------------
def timestamp_convert(value: str, to: str = "human") -> str:
    """时间戳 <-> 可读时间互转。

    Args:
        value: 时间戳（秒/毫秒）或 'now'，或可读时间字符串（to='ts' 时）。
        to: 'human' 转可读；'ts' 转时间戳（秒）。
    """
    if value.strip().lower() == "now":
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    if to == "human":
        v = value.strip()
        try:
            ts = int(v)
        except ValueError:
            # 尝试浮点（可能带小数）
            ts = float(v)
        # 毫秒级自动识别
        if ts > 1e12:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    # to == 'ts'
    dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    return str(int(dt.replace(tzinfo=timezone.utc).timestamp()))


# --------------------------------------------------------------------------
# PEM / 证书解析
# --------------------------------------------------------------------------
@dataclass
class PemInfo:
    type: str
    body_length: int
    body_preview: str


def pem_parse(text: str) -> PemInfo:
    m = re.search(r"-----BEGIN ([A-Z ]+)-----([\s\S]+?)-----END \1-----", text, re.DOTALL)
    if not m:
        raise ValueError("未识别到 PEM 块（-----BEGIN ...-----）")
    block_type = m.group(1).strip()
    body = m.group(2).strip()
    return PemInfo(type=block_type, body_length=len(body), body_preview=body[:64])


# --------------------------------------------------------------------------
# 字符串 / hex
# --------------------------------------------------------------------------
def to_hex(text: str) -> str:
    return text.encode("utf-8").hex(" ")


def from_hex(hexstr: str) -> str:
    cleaned = hexstr.strip().replace(" ", "").replace("\n", "")
    return bytes.fromhex(cleaned).decode("utf-8", errors="replace")


def string_stats(text: str) -> dict:
    return {
        "length": len(text),
        "bytes": len(text.encode("utf-8")),
        "lines": text.count("\n") + 1,
        "words": len(re.findall(r"\S+", text)),
    }
