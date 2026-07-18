"""core/ai_assist 单测：parse_intent / generate_command / lookup_kb / diagnose。"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from netops_studio.core import ai_assist as ai


# --------------------------------------------------------------------------
# parse_intent
# --------------------------------------------------------------------------
def test_parse_intent_ping_en():
    r = ai.parse_intent("ping 8.8.8.8")
    assert r["action"] == "ping"
    assert r["target"] == "8.8.8.8"


def test_parse_intent_ping_cn():
    r = ai.parse_intent("帮我 ping 一下 114.114.114.114 看通不通")
    assert r["action"] == "ping"
    assert r["target"] == "114.114.114.114"


def test_parse_intent_traceroute():
    r = ai.parse_intent("traceroute 到 1.1.1.1")
    assert r["action"] == "traceroute"
    assert r["target"] == "1.1.1.1"


def test_parse_intent_tracert_cn():
    r = ai.parse_intent("路由跟踪 192.168.1.1")
    assert r["action"] == "traceroute"
    assert r["target"] == "192.168.1.1"


def test_parse_intent_subnet_cidr():
    r = ai.parse_intent("计算子网 192.168.10.0/24")
    assert r["action"] == "subnet"
    assert r["target"] == "192.168.10.0/24"


def test_parse_intent_portscan_with_ports():
    r = ai.parse_intent("扫描 192.168.1.1 的 80 端口")
    assert r["action"] == "portscan"
    assert r["target"] == "192.168.1.1"
    assert r["params"]["ports"] == "80"


def test_parse_intent_portscan_ports_before():
    r = ai.parse_intent("端口扫描 10.0.0.1 port 443")
    assert r["action"] == "portscan"
    assert r["target"] == "10.0.0.1"
    assert r["params"]["ports"] == "443"


def test_parse_intent_scan_network():
    r = ai.parse_intent("对 10.0.0.0 网段做网络扫描")
    assert r["action"] == "scan"
    assert r["target"] == "10.0.0.0"


def test_parse_intent_speedtest():
    r = ai.parse_intent("帮我测一下带宽 speedtest")
    assert r["action"] == "speedtest"


def test_parse_intent_whois():
    r = ai.parse_intent("whois example.com 域名信息查询")
    assert r["action"] == "whois"
    assert r["target"] == "example.com"


def test_parse_intent_help_fallback():
    r = ai.parse_intent("今天天气怎么样")
    assert r["action"] == "help"


# --------------------------------------------------------------------------
# generate_command（各厂商）
# --------------------------------------------------------------------------
def test_generate_command_ping_all_vendors():
    intent = ai.parse_intent("ping 8.8.8.8")
    for v in ai.VENDORS:
        cmd = ai.generate_command(intent, v)
        assert cmd == f"ping 8.8.8.8", f"{v} -> {cmd}"


def test_generate_command_traceroute_vendors():
    intent = ai.parse_intent("traceroute 1.1.1.1")
    assert ai.generate_command(intent, "cisco") == "traceroute 1.1.1.1"
    assert ai.generate_command(intent, "huawei") == "tracert 1.1.1.1"
    assert ai.generate_command(intent, "h3c") == "tracert 1.1.1.1"
    assert ai.generate_command(intent, "juniper") == "traceroute 1.1.1.1"


def test_generate_command_subnet_network():
    intent = ai.parse_intent("子网 192.168.10.0/24")
    assert ai.generate_command(intent, "cisco") == "show ip route 192.168.10.0"
    assert ai.generate_command(intent, "juniper") == "show route 192.168.10.0"


def test_generate_command_portscan():
    intent = ai.parse_intent("端口扫描 192.168.1.1 的 80 端口")
    assert ai.generate_command(intent, "cisco") == "telnet 192.168.1.1 80"


def test_generate_command_default_vendor_unknown():
    intent = ai.parse_intent("ping 8.8.8.8")
    assert ai.generate_command(intent, "unknown") == "ping 8.8.8.8"


# --------------------------------------------------------------------------
# lookup_kb
# --------------------------------------------------------------------------
def test_lookup_kb_vlan():
    ans = ai.lookup_kb("华为交换机怎么划分 vlan 配置 trunk")
    assert "vlan" in ans.lower()


def test_lookup_kb_dhcp():
    ans = ai.lookup_kb("如何配置 dhcp 地址池")
    assert "dhcp" in ans.lower()


def test_lookup_kb_no_match():
    ans = ai.lookup_kb("今天午饭吃什么")
    assert ans == ai._DEFAULT_KB_ANSWER


# --------------------------------------------------------------------------
# diagnose
# --------------------------------------------------------------------------
def test_diagnose_packet_loss():
    steps = ai.diagnose(["丢包"])
    assert any("MTU" in s for s in steps)
    assert any("拥塞" in s for s in steps)


def test_diagnose_unreachable():
    steps = ai.diagnose(["网络不通"])
    assert any("网关" in s for s in steps)


def test_diagnose_multiple():
    steps = ai.diagnose(["丢包", "网络不通"])
    # 去重后数量应 >= 单类别步骤数
    assert len(steps) >= 4
    assert len(steps) == len(set(steps))


def test_diagnose_empty():
    steps = ai.diagnose([])
    assert len(steps) >= 1
    assert "请补充" in steps[0]


# --------------------------------------------------------------------------
# 编排 assist
# --------------------------------------------------------------------------
def test_assist_structure():
    res = ai.assist("ping 8.8.8.8", "huawei")
    assert res["intent"]["action"] == "ping"
    assert res["command"] == "ping 8.8.8.8"
    assert isinstance(res["kb_answer"], str)
    assert isinstance(res["diagnosis"], list)
