"""core/diagnostics 单测（解析逻辑 + 端口探测）。"""

import socket
import threading

import pytest

import netops_studio.core.diagnostics as diag


def test_expand_ports():
    assert diag._expand_ports("22,80,443") == [22, 80, 443]
    assert diag._expand_ports("1-3") == [1, 2, 3]
    assert diag._expand_ports("80, 1-2") == [80, 1, 2]


def test_parse_ping_linux():
    diag._SYSTEM = "linux"
    raw = (
        "PING 8.8.8.8 (8.8.8.8) 56(84) bytes of data.\n"
        "64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=10.2 ms\n"
        "--- 8.8.8.8 ping statistics ---\n"
        "4 packets transmitted, 4 received, 0% packet loss\n"
        "rtt min/avg/max/mdev = 10.1/10.5/11.0/0.3 ms\n"
    )
    r = diag._parse_ping("8.8.8.8", raw)
    assert r.transmitted == 4 and r.received == 4
    assert r.loss_percent == 0.0
    assert r.min_ms == 10.1 and r.avg_ms == 10.5 and r.max_ms == 11.0
    assert r.success


def test_parse_ping_windows():
    diag._SYSTEM = "windows"
    raw = (
        "正在 Ping 8.8.8.8 具有 32 字节的数据:\n"
        "来自 8.8.8.8 的回复: 字节=32 时间=12ms\n"
        "   已接收 = 4，丢失 = 0 (0% 丢失)，\n"
        "最短 = 10ms，最长 = 12ms，平均 = 11ms\n"
    )
    r = diag._parse_ping("8.8.8.8", raw)
    assert r.received == 4 and r.loss_percent == 0.0
    assert r.min_ms == 10.0 and r.avg_ms == 11.0 and r.max_ms == 12.0
    diag._SYSTEM = __import__("platform").system().lower()


def test_parse_ping_loss():
    diag._SYSTEM = "linux"
    raw = "3 packets transmitted, 1 received, 66% packet loss"
    r = diag._parse_ping("x", raw)
    assert r.loss_percent == 66.0


def test_port_scan_open():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    results = diag.port_scan("127.0.0.1", [port, port + 1])
    states = {r.port: r.state for r in results}
    assert states[port] == "open"
    assert states[port + 1] == "closed"
    srv.close()


def test_dns_query_no_dep(monkeypatch):
    # 无 dnspython 时优雅降级
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("dns"):
            raise ImportError("no dns")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    res = diag.dns_query("example.com")
    assert res["success"] is False
