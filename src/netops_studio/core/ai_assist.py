"""AI 智能助手核心引擎（core/ai_assist.py）。

纯 Python，禁止 import PySide6 / 任何 GUI 依赖。规则驱动、纯函数易测。
提供：意图解析、厂商命令生成、本地知识库检索、基于症状的诊断建议。

外部 LLM 仅作结构预留（assist 可插拔），默认走本地规则，无需联网。
参考开发文档 §6.x。
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from typing import Dict, List, Optional

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
ACTIONS = [
    "ping", "traceroute", "scan", "speedtest",
    "subnet", "whois", "portscan", "help",
]
VENDORS = ["cisco", "huawei", "h3c", "juniper"]

# 知识库路径：core/ai_assist.py -> ../data/kb.json
_KB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "kb.json",
)


# --------------------------------------------------------------------------
# 1. 意图解析
# --------------------------------------------------------------------------
# 关键词按优先级排列，先匹配更具体的动作。
# 顺序即优先级：更具体的动作（端口扫描/路由跟踪）排在前面，
# 通用词（扫描/子网）按动作语义靠前，保证 "网络扫描" 命中 scan 而非 subnet。
_ACTION_KEYWORDS: List[tuple[str, List[str]]] = [
    ("whois", ["whois", "域名查询", "域名信息", "whois查询", "注册信息", "whois 查询"]),
    ("speedtest", ["speedtest", "测速", "网速", "带宽测试", "带宽", "速率", "性能测试", "测带宽"]),
    ("traceroute", ["traceroute", "tracert", "路由跟踪", "路由追踪", "跟踪路由", "路径追踪"]),
    ("portscan", ["端口扫描", "扫描端口", "port scan", "portscan", "开放端口", "端口", "扫端口"]),
    ("scan", ["网络扫描", "主机发现", "资产扫描", "发现主机", "host scan", "network scan", "扫描"]),
    ("subnet", ["子网", "划分子网", "子网计算", "子网划分", "子网络", "cidr", "网段"]),
    ("ping", ["ping", "探测", "连通性", "通不通", "能不能通", "可达", "测试连通", "ping 一下"]),
    ("help", ["help", "帮助", "怎么用", "你能做什么", "功能", "使用说明", "帮我", "？", "?"]),
]

_ALL_KEYWORDS = {kw for _, kws in _ACTION_KEYWORDS for kw in kws}


def parse_intent(query: str) -> Dict[str, object]:
    """解析自然语言查询为结构化意图。

    Returns:
        {"action": str, "target": str, "params": dict}
        action ∈ ACTIONS；未匹配时回退为 "help"。
    """
    query = (query or "").strip()
    ql = query.lower()

    action = "help"
    for act, kws in _ACTION_KEYWORDS:
        if any(kw.lower() in ql for kw in kws):
            action = act
            break

    target = ""
    params: Dict[str, object] = {}

    if action == "help":
        return {"action": action, "target": target, "params": params}

    # CIDR / IP 提取
    cidr_m = re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}/\d{1,2}\b", query)
    ip_m = re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", query)

    if action == "subnet":
        target = cidr_m.group(0) if cidr_m else (ip_m.group(0) if ip_m else _extract_host(query))

    elif action in ("ping", "traceroute", "whois", "scan"):
        target = ip_m.group(0) if ip_m else _extract_host(query)

    elif action == "portscan":
        target = ip_m.group(0) if ip_m else _extract_host(query)
        params["ports"] = _extract_ports(query)

    elif action == "speedtest":
        # 测速通常无目标，若存在 IP 则记录
        target = ip_m.group(0) if ip_m else ""

    return {"action": action, "target": target, "params": params}


def _extract_host(query: str) -> str:
    """从查询中提取非关键词主机名 / 域名 token。"""
    tokens = re.findall(r"[A-Za-z0-9\.\-_]+", query)
    for t in tokens:
        tl = t.lower()
        if tl in _ALL_KEYWORDS:
            continue
        if re.fullmatch(r"\d+", t):
            continue
        if tl in ("端口", "port", "cidr", "ip"):
            continue
        return t
    return ""


def _extract_ports(query: str) -> str:
    """提取端口（支持 '80端口' / '端口 80' / 'port 80' / '端口 1-100'）。"""
    patterns = [
        r"(\d+(?:[-\s,]\d+)*)\s*端口",
        r"端口\s*[:：]?\s*(\d+(?:[-\s,]\d+)*)",
        r"port\s*[:：]?\s*(\d+(?:[-\s,]\d+)*)",
    ]
    for p in patterns:
        m = re.search(p, query, re.IGNORECASE)
        if m:
            return m.group(1).replace(" ", "")
    return "80"


# --------------------------------------------------------------------------
# 2. 厂商命令生成
# --------------------------------------------------------------------------
_COMMAND_TEMPLATES: Dict[str, Dict[str, str]] = {
    "cisco": {
        "ping": "ping {target}",
        "traceroute": "traceroute {target}",
        "portscan": "telnet {target} {ports}",
        "scan": "show ip arp",
        "speedtest": "show interfaces",
        "subnet": "show ip route {network}",
        "whois": "whois {target}",
    },
    "huawei": {
        "ping": "ping {target}",
        "traceroute": "tracert {target}",
        "portscan": "telnet {target} {ports}",
        "scan": "display arp",
        "speedtest": "display interface",
        "subnet": "display ip routing-table {network}",
        "whois": "whois {target}",
    },
    "h3c": {
        "ping": "ping {target}",
        "traceroute": "tracert {target}",
        "portscan": "telnet {target} {ports}",
        "scan": "display arp",
        "speedtest": "display interface",
        "subnet": "display ip routing-table {network}",
        "whois": "whois {target}",
    },
    "juniper": {
        "ping": "ping {target}",
        "traceroute": "traceroute {target}",
        "portscan": "telnet {target} {ports}",
        "scan": "show arp",
        "speedtest": "show interfaces",
        "subnet": "show route {network}",
        "whois": "whois {target}",
    },
}


def generate_command(intent: Dict[str, object], vendor: str = "cisco") -> str:
    """根据意图与厂商生成 CLI 命令字符串。

    Args:
        intent: parse_intent 的返回值
        vendor: cisco / huawei / h3c / juniper（未知厂商回退 cisco）
    """
    vendor = (vendor or "cisco").lower()
    if vendor not in _COMMAND_TEMPLATES:
        vendor = "cisco"

    action = intent.get("action", "help")
    templates = _COMMAND_TEMPLATES[vendor]
    if action not in templates:
        return ""

    target = str(intent.get("target", "") or "")
    params = intent.get("params", {}) or {}
    ports = str(params.get("ports", "80") if isinstance(params, dict) else "80")

    # subnet 动作需拆出 network（CIDR 网络地址）
    network = target
    if action == "subnet" and "/" in target:
        net_addr, _ = _net_of(target)
        network = net_addr

    try:
        return templates[action].format(target=target, ports=ports, network=network)
    except (KeyError, IndexError):
        return templates[action]


def _net_of(cidr: str) -> tuple[str, str]:
    """返回 (网络地址, 子网掩码)。"""
    try:
        net = ipaddress.ip_network(cidr.strip(), strict=False)
        return str(net.network_address), str(net.netmask)
    except ValueError:
        return cidr, "255.255.255.0"


# --------------------------------------------------------------------------
# 3. 本地知识库检索
# --------------------------------------------------------------------------
_DEFAULT_KB_ANSWER = (
    "未找到匹配的本地知识库条目。可尝试更换关键词，或将问题提交给在线知识库。"
)


def _load_kb() -> List[Dict[str, object]]:
    if not os.path.isfile(_KB_PATH):
        return []
    try:
        with open(_KB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data["entries"]
        return []
    except (json.JSONDecodeError, OSError):
        return []


def lookup_kb(question: str) -> str:
    """基于关键词在本地 kb.json 中检索答案。

    返回匹配度最高（命中关键词最多）条目的 answer；无匹配返回默认提示。
    """
    question = (question or "").lower()
    entries = _load_kb()
    if not entries:
        return _DEFAULT_KB_ANSWER

    best: Optional[str] = None
    best_score = 0
    for entry in entries:
        kws = entry.get("keywords", []) or entry.get("keyword", []) or []
        if isinstance(kws, str):
            kws = [kws]
        score = sum(1 for k in kws if str(k).lower() in question)
        if score > best_score:
            best_score = score
            best = entry.get("answer", "")
    if best is not None and best_score > 0:
        return str(best)
    return _DEFAULT_KB_ANSWER


# --------------------------------------------------------------------------
# 4. 基于症状的诊断建议
# --------------------------------------------------------------------------
_SYMPTOM_RULES: List[tuple[str, List[str], List[str]]] = [
    ("丢包", ["丢包", "packet loss", "loss", "掉包", "丢包率"], [
        "检查链路物理状态（光衰、网线、接口 up/down）",
        "检查 MTU 是否两端一致（排查分片与黑洞路由）",
        "检查是否存在拥塞（接口利用率、队列丢包计数）",
        "排查 ACL / 策略路由是否丢弃报文",
    ]),
    ("延迟高", ["延迟", "latency", "高延迟", "卡顿", "慢", "slow", "rtt", "延时"], [
        "检查链路带宽利用率与拥塞情况",
        "使用 traceroute 查看路径跳数与异常跳",
        "检查是否存在非对称路由或路由环路",
        "排查 QoS 策略与优先级队列配置",
    ]),
    ("网络不通", ["不通", "不可达", "unreachable", "无法访问", "连不上", "timeout", "超时", "断网", "不能访问"], [
        "检查本端 IP / 掩码 / 网关配置",
        "检查对端是否在线及防火墙策略",
        "检查路由表（缺省路由、明细路由）是否正确",
        "检查 ACL / 安全组是否拦截",
    ]),
    ("DNS 解析", ["dns", "域名", "解析", "resolve", "域名解析"], [
        "检查 DNS 服务器地址配置是否正确",
        "使用 nslookup / dig 验证解析结果",
        "检查 DNS 防火墙与安全策略是否拦截 53 端口",
    ]),
    ("链路震荡", ["震荡", "flapping", "抖动", "频繁断开", "up down"], [
        "检查物理链路与光模块（收发光功率）",
        "检查 STP / 环路状态与根桥选举",
        "检查双工 / 速率协商是否匹配",
    ]),
]


def extract_symptoms(query: str) -> List[str]:
    """从自然语言描述中提取命中的症状类别标签。"""
    ql = (query or "").lower()
    found: List[str] = []
    for label, kws, _ in _SYMPTOM_RULES:
        if any(kw.lower() in ql for kw in kws):
            found.append(label)
    return found


def diagnose(symptoms: List[str]) -> List[str]:
    """根据症状列表返回去重后的建议排查步骤。

    Args:
        symptoms: 症状类别标签（来自 extract_symptoms）或原始描述词。
    Returns:
        建议步骤列表（中文）；无匹配时返回通用引导。
    """
    syms = [str(s).lower() for s in (symptoms or [])]
    steps: List[str] = []
    seen: set[str] = set()

    # 支持直接传入原始描述（包含关键词即触发对应规则）
    for label, kws, step_list in _SYMPTOM_RULES:
        triggered = label.lower() in syms or any(
            kw.lower() in s for s in syms for kw in kws
        )
        if triggered:
            for s in step_list:
                if s not in seen:
                    seen.add(s)
                    steps.append(s)

    if not steps:
        return [
            "请补充更具体的故障现象（如：丢包 / 延迟高 / 网络不通 / DNS 解析失败）以便精准排查。",
            "可尝试先用 AI 助手生成 ping / traceroute 命令做初步定位。",
        ]
    return steps


# --------------------------------------------------------------------------
# 编排：一次性给出意图 / 命令 / 知识库 / 诊断
# --------------------------------------------------------------------------
def assist(query: str, vendor: str = "cisco") -> Dict[str, object]:
    """综合处理一条自然语言查询。

    返回结构化结果，供 GUI 渲染；纯计算、同步、无需外部 LLM。
    外部 LLM 可在此处替换 lookup_kb / diagnose 实现（结构预留）。
    """
    intent = parse_intent(query)
    action = intent.get("action", "help")

    command = ""
    if action != "help":
        command = generate_command(intent, vendor)

    kb_answer = lookup_kb(query)
    diagnosis = diagnose(extract_symptoms(query))

    return {
        "intent": intent,
        "command": command,
        "kb_answer": kb_answer,
        "diagnosis": diagnosis,
    }
