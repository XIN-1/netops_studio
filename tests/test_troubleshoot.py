"""core/troubleshoot 单测（多厂商 ARP 解析、IP 冲突、环路检测）。"""

from netops_studio.core import troubleshoot as ts

CISCO_ARP = """\
Protocol  Address          Age (min)  Hardware Addr   Type   Interface
Internet  10.0.0.1         -          aabb.cc00.0101  ARPA   GigabitEthernet0/1
Internet  10.0.0.2         12         aabb.cc00.0202  ARPA   GigabitEthernet0/2
Internet  10.0.0.3         5          aabb.cc00.0303  ARPA   Vlan10
"""

HUAWEI_ARP = """\
IP ADDRESS      MAC ADDRESS     EXPIRE(M) TYPE INTERFACE      VPN-INSTANCE
                                          VLAN/CEVLAN
10.0.0.1        aabb-cc00-0101  1         D-0  GE0/0/1         public
10.0.0.2        aabb-cc00-0202  20        D-0  GE0/0/2         public
"""

H3C_ARP = """\
          Type: S-Static   D-Dynamic   O-Openflow   R-Rule   M-Multiport  I-Invalid
IP ADDRESS      MAC ADDRESS     VLAN/VVLAN INTERFACE                AGING TYPE
10.0.0.1        aabb-cc00-0101 1/1        GE1/0/1                   20    D
10.0.0.2        aabb-cc00-0202 1/1        GE1/0/2                   15    D
"""

JUNIPER_ARP = """\
MAC Address       Address         Name     Interface     Flags
00:11:22:33:44:55 10.0.0.1        host1    ge-0/0/0.0    none
aa:bb:cc:dd:ee:ff 10.0.0.2        host2    ge-0/0/1.0    none
"""


# --------------------------------------------------------------------------
# 多厂商 ARP 解析
# --------------------------------------------------------------------------
def test_parse_arp_cisco():
    entries = ts.parse_arp_table("cisco", CISCO_ARP)
    assert len(entries) == 3
    assert entries[0] == {"ip": "10.0.0.1", "mac": "aabb.cc00.0101",
                          "interface": "GigabitEthernet0/1"}


def test_parse_arp_huawei():
    entries = ts.parse_arp_table("huawei", HUAWEI_ARP)
    assert len(entries) == 2
    assert entries[0] == {"ip": "10.0.0.1", "mac": "aabb-cc00-0101",
                          "interface": "GE0/0/1"}


def test_parse_arp_h3c():
    entries = ts.parse_arp_table("h3c", H3C_ARP)
    assert len(entries) == 2
    assert entries[1] == {"ip": "10.0.0.2", "mac": "aabb-cc00-0202",
                          "interface": "GE1/0/2"}


def test_parse_arp_juniper():
    entries = ts.parse_arp_table("juniper", JUNIPER_ARP)
    assert len(entries) == 2
    assert entries[0] == {"ip": "10.0.0.1", "mac": "00:11:22:33:44:55",
                          "interface": "ge-0/0/0.0"}


def test_parse_arp_vendor_alias():
    # device_type 形式也能识别
    entries = ts.parse_arp_table("cisco_ios", CISCO_ARP)
    assert len(entries) == 3


# --------------------------------------------------------------------------
# IP 冲突
# --------------------------------------------------------------------------
def test_detect_ip_conflict():
    entries = [
        {"ip": "10.0.0.1", "mac": "aabb.cc00.0101", "interface": "Gi0/1"},
        {"ip": "10.0.0.1", "mac": "aabb.cc00.9999", "interface": "Gi0/2"},
        {"ip": "10.0.0.2", "mac": "aabb.cc00.0202", "interface": "Gi0/3"},
    ]
    conflicts = ts.detect_ip_conflict(entries)
    assert len(conflicts) == 1
    assert conflicts[0]["ip"] == "10.0.0.1"
    assert set(conflicts[0]["macs"]) == {"aabb.cc00.0101", "aabb.cc00.9999"}


def test_detect_ip_conflict_none():
    entries = [
        {"ip": "10.0.0.1", "mac": "aabb.cc00.0101", "interface": "Gi0/1"},
        {"ip": "10.0.0.1", "mac": "aabb.cc00.0101", "interface": "Gi0/2"},
    ]
    assert ts.detect_ip_conflict(entries) == []


def test_detect_ip_conflict_via_parse():
    # 同一 IP 在 Cisco ARP 表中出现两个不同 MAC（点分格式），应判定冲突
    text = (
        "Internet  10.0.0.9         -          aabb.cc00.0109  ARPA   GigabitEthernet0/9\n"
        "Internet  10.0.0.9         5          aabb.cc00.9999  ARPA   GigabitEthernet0/10\n"
    )
    entries = ts.parse_arp_table("cisco", text)
    assert len(entries) == 2
    conflicts = ts.detect_ip_conflict(entries)
    assert len(conflicts) == 1
    assert conflicts[0]["ip"] == "10.0.0.9"
    assert set(conflicts[0]["macs"]) == {"aabb.cc00.0109", "aabb.cc00.9999"}


# --------------------------------------------------------------------------
# 环路 / STP 异常（重复 MAC 跨端口）
# --------------------------------------------------------------------------
def test_detect_loop_mac_flap():
    entries = [
        {"ip": "10.0.0.1", "mac": "aabb.cc00.0101", "interface": "Gi0/1"},
        {"ip": "10.0.0.2", "mac": "aabb.cc00.0101", "interface": "Gi0/2"},
    ]
    anomalies = ts.detect_loop(entries, {})
    flaps = [a for a in anomalies if a["type"] == "mac_flap"]
    assert len(flaps) == 1
    assert flaps[0]["mac"] == "aabbcc000101"
    assert "Gi0/1" in flaps[0]["port"] and "Gi0/2" in flaps[0]["port"]


def test_detect_loop_no_anomaly():
    entries = [
        {"ip": "10.0.0.1", "mac": "aabb.cc00.0101", "interface": "Gi0/1"},
        {"ip": "10.0.0.2", "mac": "aabb.cc00.0202", "interface": "Gi0/2"},
    ]
    assert ts.detect_loop(entries, {"root": "aabb.cc00.0001"}) == []


def test_detect_loop_no_root():
    anomalies = ts.detect_loop([], {"root": None})
    assert any(a["type"] == "no_root" for a in anomalies)


# --------------------------------------------------------------------------
# STP 解析（阻塞端口）
# --------------------------------------------------------------------------
def test_parse_spanning_tree_cisco():
    text = """\
Root ID    Priority    32769
           Address     aabb.cc00.0100
Interface           Role Sts Cost      Prio.Nbr Type
Gi0/1               Root FWD 19        128.1    P2p
Gi0/2               Altn BLK 19        128.2    P2p
"""
    info = ts.parse_spanning_tree(text)
    assert info["root"] == "aabb.cc00.0100"
    assert "Gi0/2" in info["blocked_ports"]


def test_parse_spanning_tree_huawei():
    text = """\
CIST Root/ERPC      : aabb-cc00-0200 / 2000
Port                        Role        STP State
GigabitEthernet0/0/1        DESI        FORWARDING
GigabitEthernet0/0/2        ALTE        DISCARDING
"""
    info = ts.parse_spanning_tree(text)
    assert info["root"] == "aabb-cc00-0200"
    assert "GigabitEthernet0/0/2" in info["blocked_ports"]
