"""core/integration 单测：CSV / JSON 转换往返（纯函数，不依赖 fastapi / 网络）。"""

import netops_studio.core.integration as integ
from netops_studio.core.discovery import Host


def _sample():
    return [
        Host(ip="192.168.1.1", hostname="gw", mac="00:11:22:33:44:55",
             vendor="Cisco", state="up", latency_ms=1.2),
        Host(ip="192.168.1.10", hostname="", mac="", vendor="", state="up", latency_ms=None),
    ]


def test_devices_to_csv_roundtrip():
    devices = _sample()
    csv_text = integ.devices_to_csv(devices)
    back = integ.csv_to_devices(csv_text)
    assert len(back) == len(devices)
    for a, b in zip(devices, back):
        assert a.ip == b.ip
        assert a.hostname == b.hostname
        assert a.mac == b.mac
        assert a.vendor == b.vendor
        assert a.state == b.state
        assert a.latency_ms == b.latency_ms


def test_devices_to_json_roundtrip():
    devices = _sample()
    json_text = integ.devices_to_json(devices)
    back = integ.json_to_devices(json_text)
    assert len(back) == len(devices)
    for a, b in zip(devices, back):
        assert a == b


def test_devices_to_csv_header():
    csv_text = integ.devices_to_csv(_sample())
    header = csv_text.splitlines()[0]
    assert header == "ip,hostname,mac,vendor,state,latency_ms"


def test_csv_to_devices_empty():
    assert integ.csv_to_devices("") == []


def test_json_to_devices_requires_list():
    import pytest
    with pytest.raises(ValueError):
        integ.json_to_devices('{"ip": "1.1.1.1"}')


def test_conversion_accepts_dicts():
    raw = [{"ip": "10.0.0.1", "hostname": "srv", "state": "down"}]
    csv_text = integ.devices_to_csv(raw)
    back = integ.csv_to_devices(csv_text)
    assert back[0].ip == "10.0.0.1"
    assert back[0].hostname == "srv"
    assert back[0].state == "down"
    assert back[0].latency_ms is None
