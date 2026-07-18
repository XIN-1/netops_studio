"""core/capture 单测：纯解析函数（不依赖 tshark 二进制）。

覆盖 parse_conversations / protocol_stats / detect_anomalies。
"""

import netops_studio.core.capture as cap


# 样例 tshark 输出：tshark -r file -q -z conv,ip
CONV_TEXT = """\
================================================================================
IPv4 Conversations
Filter:ip
                                               |       <-      |       ->      |     Total    |   Rel Start   |   Duration   |
                                               | Frames  Bytes | Frames  Bytes | Frames Bytes |               |              |
192.168.1.10        <-> 192.168.1.1                   5       420       3       240       8      660   0.000000000   1.200000000
192.168.1.10        <-> 192.168.1.2                   1       100       2       200       3      300   0.500000000   0.800000000
================================================================================
"""

# 样例 tshark 输出：tshark -r file -q -z io,phs
PHS_TEXT = """\
================================================================================
Protocol Hierarchy Statistics
Filter:

eth                                    frames:8 bytes:960
  ip                                   frames:8 bytes:960
    udp                                frames:3 bytes:300
    tcp                                frames:5 bytes:660
================================================================================
"""


def test_parse_conversations():
    convs = cap.parse_conversations(CONV_TEXT)
    assert len(convs) == 2
    c0 = convs[0]
    assert c0["src"] == "192.168.1.10"
    assert c0["dst"] == "192.168.1.1"
    assert c0["packets"] == 8
    assert c0["bytes"] == 660
    c1 = convs[1]
    assert c1["src"] == "192.168.1.10"
    assert c1["dst"] == "192.168.1.2"
    assert c1["packets"] == 3
    assert c1["bytes"] == 300


def test_parse_conversations_ipv6_bracket():
    text = "[fe80::1]:546        <-> [fe80::2]:547                   1        64       1        64       2      128   0.0   0.1"
    convs = cap.parse_conversations(text)
    assert len(convs) == 1
    assert convs[0]["src"] == "[fe80::1]:546"
    assert convs[0]["dst"] == "[fe80::2]:547"
    assert convs[0]["packets"] == 2 and convs[0]["bytes"] == 128


def test_protocol_stats():
    stats = cap.protocol_stats(PHS_TEXT)
    assert stats == {"eth": 960, "ip": 960, "udp": 300, "tcp": 660}


def test_protocol_stats_indent_independent():
    text = "tcp   frames:2 bytes:160\n  ip  frames:5 bytes:960"
    stats = cap.protocol_stats(text)
    # 同名协议聚合
    assert stats["tcp"] == 160
    assert stats["ip"] == 960


def test_detect_anomalies_single_ip_dominance():
    records = [
        {"src": "192.168.1.10", "dst": "192.168.1.1", "packets": 8, "bytes": 660},
        {"src": "192.168.1.10", "dst": "192.168.1.2", "packets": 3, "bytes": 300},
    ]
    anoms = cap.detect_anomalies(records)
    types = [a["type"] for a in anoms]
    assert "single_ip_dominance" in types
    dom = next(a for a in anoms if a["type"] == "single_ip_dominance")
    assert dom["detail"]["ip"] == "192.168.1.10"
    assert dom["detail"]["ratio"] == 1.0


def test_detect_anomalies_no_false_positive():
    # 三组互不重叠的会话：任一 IP 字节占比 = 1/3 < 0.5，不应触发异常
    records = [
        {"src": "10.0.0.1", "dst": "10.0.0.2", "packets": 1, "bytes": 100},
        {"src": "10.0.0.3", "dst": "10.0.0.4", "packets": 1, "bytes": 100},
        {"src": "10.0.0.5", "dst": "10.0.0.6", "packets": 1, "bytes": 100},
    ]
    assert cap.detect_anomalies(records) == []


def test_detect_anomalies_fanout():
    # 单源与 25 个不同目标通信 -> 疑似 ARP 风暴 / 扫描
    records = [
        {"src": "10.0.0.5", "dst": f"10.0.0.{i}", "packets": 1, "bytes": 60}
        for i in range(25)
    ]
    anoms = cap.detect_anomalies(records)
    fan = [a for a in anoms if a["type"] == "conversation_fanout"]
    assert fan, "应检测到会话扇出异常"
    assert fan[0]["detail"]["ip"] == "10.0.0.5"
    assert fan[0]["detail"]["distinct_dst"] == 25


def test_detect_anomalies_empty():
    assert cap.detect_anomalies([]) == []


def test_find_tshark_missing_raises(monkeypatch):
    # 模拟 resources 无自带二进制且系统无 tshark
    monkeypatch.setattr(cap, "_RESOURCE_BIN", {})
    monkeypatch.setattr(cap.shutil, "which", lambda _: None)
    try:
        cap.find_tshark(pkg_root="/nonexistent")
    except cap.TsharkNotFoundError:
        return
    raise AssertionError("缺失 tshark 时应当抛出 TsharkNotFoundError")
