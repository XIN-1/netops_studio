"""core/subnet 单测。"""

import pytest

from netops_studio.core.subnet import calculate, subnet_split, ip_in_network


def test_calculate_basic():
    r = calculate("192.168.1.0/24")
    assert r.network == "192.168.1.0"
    assert r.prefixlen == 24
    assert r.host_count == 256
    assert r.usable == 254
    assert r.first_host == "192.168.1.1"
    assert r.last_host == "192.168.1.254"
    assert r.broadcast == "192.168.1.255"


def test_calculate_loose():
    # 宽松模式自动归整到网络地址
    r = calculate("192.168.1.130/24")
    assert r.network == "192.168.1.0"


def test_calculate_prefix30():
    r = calculate("10.0.0.0/30")
    assert r.usable == 2
    assert r.first_host == "10.0.0.1"
    assert r.last_host == "10.0.0.2"


def test_subnet_split():
    subs = subnet_split("192.168.0.0/24", 26)
    assert len(subs) == 4
    assert subs[0].network == "192.168.0.0"
    assert subs[-1].network == "192.168.0.192"
    for s in subs:
        assert s.prefixlen == 26


def test_subnet_split_invalid():
    with pytest.raises(ValueError):
        subnet_split("192.168.0.0/24", 24)


def test_ip_in_network():
    assert ip_in_network("192.168.1.50", "192.168.1.0/24")
    assert not ip_in_network("10.0.0.1", "192.168.1.0/24")
