"""core/codec 单测。"""

import pytest

from netops_studio.core import codec


def test_base64_roundtrip():
    s = "Hello, NetOps! 网维"
    enc = codec.base64_encode(s)
    assert codec.base64_decode(enc) == s


def test_base64_with_padding():
    # 缺填充也应能解
    assert codec.base64_decode("SGVsbG8") == "Hello"


def test_url_encode():
    assert codec.url_encode("a b&c") == "a%20b%26c"
    assert codec.url_decode("a%20b%26c") == "a b&c"


def test_convert_base():
    assert codec.convert_base("255", 10, 16) == "FF"
    assert codec.convert_base("11111111", 2, 10) == "255"
    assert codec.convert_base("ff", 16, 2) == "11111111"


def test_convert_base_invalid():
    with pytest.raises(ValueError):
        codec.convert_base("zz", 10, 16)


def test_hash_data():
    assert codec.hash_data("abc", "md5") == "900150983cd24fb0d6963f7d28e17f72"
    assert codec.hash_data("abc", "sha256").startswith("ba7816")
    assert len(codec.hash_data("abc", "crc32")) == 8


def test_jwt_parse():
    import base64, json
    h = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({"sub": "1", "name": "ops"}).encode()).rstrip(b"=").decode()
    sig = "dummy_signature"
    tok = f"{h}.{p}.{sig}"
    res = codec.jwt_parse(tok)
    assert res.header["alg"] == "HS256"
    assert res.payload["sub"] == "1"


def test_timestamp_convert():
    # 固定时间戳 -> 可读（UTC）
    out = codec.timestamp_convert("1700000000")
    assert out.startswith("2023-11-14")
    # now -> 可读
    assert "UTC" in codec.timestamp_convert("now")
    # 可读 -> 时间戳
    ts = codec.timestamp_convert("2023-11-14 22:13:20", to="ts")
    assert ts == "1700000000"


def test_pem_parse():
    pem = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----"
    info = codec.pem_parse(pem)
    assert info.type == "CERTIFICATE"
    assert info.body_length == 4
