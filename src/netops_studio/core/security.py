"""安全管理引擎（core/security.py）。

纯 Python，**禁止 import PySide6**。重依赖（cryptography）函数内惰性 import。
提供：开放端口审计、弱口令检测、证书过期监控、本地 CVE 查询、防火墙规则审计。
参考开发文档 §6.4。所有函数返回结构化 dataclass / dict，由 GUI 渲染。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .diagnostics import port_scan
from . import codec


# --------------------------------------------------------------------------
# 1. 开放端口审计
# --------------------------------------------------------------------------
@dataclass
class PortAuditResult:
    target: str
    total: int
    open_ports: List[int] = field(default_factory=list)
    results: list = field(default_factory=list)  # List[PortScanResult]


def audit_ports(target: str, ports) -> PortAuditResult:
    """复用 diagnostics.port_scan 探测端口并汇总开放端口。

    Args:
        target: 目标主机/IP。
        ports: 端口（int / str "22,80,443" / list[int]），原样交给 port_scan。
    """
    results = port_scan(target, ports)
    open_ports = [r.port for r in results if r.state == "open"]
    return PortAuditResult(
        target=target,
        total=len(results),
        open_ports=open_ports,
        results=results,
    )


# --------------------------------------------------------------------------
# 2. 弱口令检测
# --------------------------------------------------------------------------
# 常见弱口令字典（小写归一后比较），用于 check_password_strength / is_weak 命中判断
COMMON_WEAK = {
    "123456", "12345678", "123456789", "password", "passw0rd", "qwerty",
    "abc123", "111111", "123123", "000000", "admin", "root", "toor",
    "guest", "default", "letmein", "welcome", "monkey", "iloveyou",
    "changeme", "1q2w3e4r", "password1", "1qaz2wsx",
}


def check_password_strength(pw: str) -> Dict[str, Any]:
    """评估口令强度，返回 {'score':int(0-100), 'issues':[...]}。纯函数。"""
    issues: List[str] = []
    score = 0

    length = len(pw)
    if length >= 12:
        score += 40
    elif length >= 8:
        score += 25
    else:
        issues.append("密码长度不足 8 位")

    if any(c.isupper() for c in pw):
        score += 15
    else:
        issues.append("缺少大写字母")

    if any(c.islower() for c in pw):
        score += 15
    else:
        issues.append("缺少小写字母")

    if any(c.isdigit() for c in pw):
        score += 15
    else:
        issues.append("缺少数字")

    specials = "!@#$%^&*()-_=+[]{};:,.<>?/|~`"
    if any(c in specials for c in pw):
        score += 15
    else:
        issues.append("缺少特殊字符")

    # 字典命中可直接判弱
    if pw in COMMON_WEAK:
        score = 0
        issues.insert(0, "命中常见弱口令字典")

    # 重复字符过多
    if length > 0 and len(set(pw)) <= length / 3:
        score = max(0, score - 20)
        issues.append("字符重复度过高")

    score = max(0, min(100, score))
    return {"score": score, "issues": issues}


def is_weak(pw: str) -> bool:
    """纯函数：口令是否命中弱口令字典。"""
    return pw in COMMON_WEAK


# --------------------------------------------------------------------------
# 3. 证书过期监控
# --------------------------------------------------------------------------
@dataclass
class CertExpiry:
    type: str
    not_after: datetime
    days_left: int


def parse_cert_expiry(pem_text: str) -> CertExpiry:
    """解析 PEM 证书到期时间。惰性 import cryptography.x509。

    复用 codec.pem_parse 取出块类型；缺失 cryptography 抛清晰错误。
    """
    try:
        from cryptography import x509
    except ImportError as exc:  # 重依赖，缺失时给出明确指引
        raise RuntimeError(
            "缺少 cryptography 库，无法解析证书。请运行：pip install cryptography"
        ) from exc

    # 复用 codec.pem_parse 取类型（非法 PEM 会抛 ValueError）
    info = codec.pem_parse(pem_text)
    pem_type = info.type

    try:
        cert = x509.load_pem_x509_certificate(pem_text.encode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"证书解析失败：{exc}") from exc

    try:  # cryptography >= 42
        not_after = cert.not_valid_after_utc
    except AttributeError:
        not_after = cert.not_valid_after.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    days_left = (not_after - now).days
    return CertExpiry(type=pem_type, not_after=not_after, days_left=days_left)


# --------------------------------------------------------------------------
# 4. 本地 CVE 查询
# --------------------------------------------------------------------------
_CVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "cve.json")


def lookup_cve(product: str) -> List[Dict[str, Any]]:
    """按 product 在本地 data/cve.json 中模糊查询。文件缺失返回空列表。"""
    if not os.path.isfile(_CVE_PATH):
        return []
    try:
        with open(_CVE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    records = data.get("records", []) if isinstance(data, dict) else data
    if not product:
        return list(records)
    key = product.strip().lower()
    return [r for r in records if key in str(r.get("product", "")).lower()]


# --------------------------------------------------------------------------
# 5. 防火墙规则审计
# --------------------------------------------------------------------------
@dataclass
class FirewallAuditResult:
    total: int
    violations: List[str] = field(default_factory=list)
    unused: List[int] = field(default_factory=list)  # 被遮蔽的冗余规则行号


def audit_firewall(config_text: str) -> FirewallAuditResult:
    """简单解析类 Cisco ACL 文本，找出违规与冗余规则。纯函数。

    识别：
    - any/any permit（过宽放行，如 'permit ip any any'）
    - 含 'any any' 的 permit 行
    - 宽泛 permit 之后的后续规则被其遮蔽（视为未使用）
    """
    violations: List[str] = []
    unused: List[int] = []
    total = 0
    shadow_started = False
    any_any_permit = False

    for idx, raw_line in enumerate(config_text.splitlines(), start=1):
        line = raw_line.strip()
        # 跳过空行与注释行（! 为 Cisco 风格，# 为通用风格）
        if not line or line.startswith("!") or line.startswith("#"):
            continue
        total += 1
        low = line.lower()

        # 过宽放行：permit ip any any / permit tcp any any ...
        # 判定依据：含 permit、且 any 出现 >=2 次（源+目的各一）、且动作含 ip/tcp/udp。
        if "permit" in low and "any" in low:
            # 统计 any 出现次数（通常源+目的各一个）
            if low.count("any") >= 2 and ("ip" in low or "tcp" in low or "udp" in low or "any any" in low):
                if not any_any_permit:
                    any_any_permit = True
                    shadow_started = True
                    violations.append(f"行 {idx}: 检测到 any/any 全放行——过度开放：{raw_line.strip()}")
                else:
                    # 已存在 any/any，本条为冗余遮蔽
                    unused.append(idx)
                    violations.append(f"行 {idx}: any/any 之后被遮蔽的冗余规则：{raw_line.strip()}")
                continue

        # 已被 any/any 遮蔽的后续 permit/deny
        if shadow_started:
            unused.append(idx)
            violations.append(f"行 {idx}: 已被前置 any/any 规则遮蔽（永不命中）：{raw_line.strip()}")

    if not any_any_permit and total > 0:
        # 没有发现任何放行规则，提示可能默认全阻或缺少显式 permit
        violations.append("未检测到显式 permit 规则，请确认默认策略与放行意图。")

    return FirewallAuditResult(total=total, violations=violations, unused=unused)
