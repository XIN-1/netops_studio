"""工具箱单元测试（tests/test_toolbox.py）。"""

from __future__ import annotations

import pytest

from netops_studio.core.toolbox import (
    bandwidth, build_wol, gen_password, mask_to_wildcard, oui_lookup,
    unit_convert, wildcard_to_mask,
)


# ----------------------------------------------------------------- 掩码互转
def test_mask_to_wildcard():
    assert mask_to_wildcard("255.255.255.0") == "0.0.0.255"
    assert mask_to_wildcard("255.255.0.0") == "0.0.255.255"
    assert mask_to_wildcard("255.255.255.128") == "0.0.0.127"
    assert mask_to_wildcard("0.0.0.0") == "255.255.255.255"


def test_wildcard_to_mask():
    assert wildcard_to_mask("0.0.0.255") == "255.255.255.0"
    assert wildcard_to_mask("0.0.255.255") == "255.255.0.0"
    assert wildcard_to_mask("255.255.255.255") == "0.0.0.0"


def test_mask_wildcard_roundtrip():
    for m in ["255.255.255.0", "255.255.255.128", "255.0.0.0", "255.255.255.252"]:
        assert wildcard_to_mask(mask_to_wildcard(m)) == m
        assert mask_to_wildcard(wildcard_to_mask(m)) == m


# ----------------------------------------------------------------- OUI
def test_oui_lookup_known():
    assert oui_lookup("00:0C:29:AB:CD:EF") == "VMware"
    assert oui_lookup("AC-1F-6B-12-34-56") == "Huawei"
    assert oui_lookup("001A.2B33.4455") == "Cisco"
    assert oui_lookup("B0C5.04AA.BBCC") == "Apple"


def test_oui_lookup_unknown():
    assert oui_lookup("00:00:00:00:00:00") == ""
    assert oui_lookup("DE:AD:BE:EF:00:11") == ""


# -------------------------------------------------------------- 密码策略
def test_gen_password_default_length():
    p = gen_password()
    assert len(p) == 16


def test_gen_password_length_only_digits():
    p = gen_password(24, upper=False, lower=False, digit=True, symbol=False)
    assert len(p) == 24
    assert p.isdigit()


def test_gen_password_all_categories_present():
    p = gen_password(20, upper=True, lower=True, digit=True, symbol=True)
    assert any(c.isupper() for c in p)
    assert any(c.islower() for c in p)
    assert any(c.isdigit() for c in p)
    assert any(c in "!@#$%^&*()-_=+[]{};:,.<>?" for c in p)


def test_gen_password_short_ensures_categories():
    # 长度小于类别数时，仍保证每个类别至少出现一次
    p = gen_password(2, upper=True, lower=True, digit=True, symbol=True)
    assert len(p) == 4
    assert any(c.isupper() for c in p)
    assert any(c.islower() for c in p)
    assert any(c.isdigit() for c in p)


def test_gen_password_no_pool_raises():
    with pytest.raises(ValueError):
        gen_password(8, upper=False, lower=False, digit=False, symbol=False)


# -------------------------------------------------------------- 带宽
def test_bandwidth_basic():
    # 1 MB 在 1 秒内 => 8 Mbps
    assert bandwidth(1_000_000, 1) == 8.0
    assert bandwidth(1_000_000, 1, overhead=1.0) == 8.0


def test_bandwidth_overhead_and_seconds():
    # 2 MB 在 2 秒、1.25 开销 => 2*8*1.25/2/1e6 * 1e6 = 10 Mbps
    assert bandwidth(2_000_000, 2, overhead=1.25) == 10.0


def test_bandwidth_invalid_seconds():
    with pytest.raises(ValueError):
        bandwidth(1000, 0)


# -------------------------------------------------------------- 单位换算
def test_unit_convert_decimal_data():
    assert unit_convert(1, "KB", "B") == 1000
    assert unit_convert(1, "MB", "KB") == 1000
    assert unit_convert(1000, "KB", "MB") == pytest.approx(1.0)


def test_unit_convert_binary_data():
    assert unit_convert(1, "KiB", "B") == 1024
    assert unit_convert(1, "MiB", "KiB") == 1024


def test_unit_convert_rate():
    assert unit_convert(1, "Mbps", "kbps") == 1000
    assert unit_convert(1, "Gbps", "Mbps") == 1000


def test_unit_convert_mismatch_raises():
    with pytest.raises(ValueError):
        unit_convert(1, "KB", "bps")
    with pytest.raises(ValueError):
        unit_convert(1, "Mbps", "MB")


# -------------------------------------------------------------- WOL
def test_build_wol():
    pkt = build_wol("00:11:22:33:44:55")
    assert isinstance(pkt, bytes)
    assert len(pkt) == 102
    assert pkt[:6] == b"\xff" * 6
    assert pkt[6:12] == bytes.fromhex("001122334455")
    assert pkt == b"\xff" * 6 + bytes.fromhex("001122334455") * 16


def test_build_wol_dash_format():
    pkt = build_wol("00-11-22-33-44-55")
    assert pkt == b"\xff" * 6 + bytes.fromhex("001122334455") * 16


def test_build_wol_invalid():
    with pytest.raises(ValueError):
        build_wol("not-a-mac")
