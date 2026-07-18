"""core/security 单测：弱口令、证书解析、端口审计、CVE 查询。"""

import datetime
import socket

import pytest

import netops_studio.core.security as sec


# --------------------------------------------------------------------------
# 弱口令
# --------------------------------------------------------------------------
def test_is_weak():
    assert sec.is_weak("123456")
    assert sec.is_weak("admin")
    assert not sec.is_weak("Tr0ub4dour&3")  # 强口令不在字典


def test_check_password_strength_weak():
    r = sec.check_password_strength("123456")
    assert r["score"] == 0
    assert any("弱口令" in i for i in r["issues"])


def test_check_password_strength_strong():
    r = sec.check_password_strength("Tr0ub4dour&3xyz")
    assert r["score"] >= 80
    assert r["issues"] == []


def test_check_password_strength_short():
    r = sec.check_password_strength("ab1")
    assert r["score"] < 60
    assert any("长度" in i for i in r["issues"])


# --------------------------------------------------------------------------
# 证书解析（用 cryptography 生成自签名证书）
# --------------------------------------------------------------------------
def _make_self_signed(days: int):
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    import datetime as dt

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test.local")])
    not_after = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime.now(dt.timezone.utc))
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("utf-8")


def test_parse_cert_expiry():
    pem = _make_self_signed(days=90)
    res = sec.parse_cert_expiry(pem)
    assert res.type == "CERTIFICATE"
    assert isinstance(res.not_after, datetime.datetime)
    assert 85 <= res.days_left <= 95


def test_parse_cert_expiry_missing_crypto(monkeypatch):
    # 先生成证书文本（此时 cryptography 可用），再屏蔽导入以验证降级报错
    pem = _make_self_signed(days=10)
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name.startswith("cryptography"):
            raise ImportError("no cryptography")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(RuntimeError, match="cryptography"):
        sec.parse_cert_expiry(pem)


# --------------------------------------------------------------------------
# 端口审计（起本地 socket，仿 test_diagnostics.py）
# --------------------------------------------------------------------------
def test_audit_ports():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    res = sec.audit_ports("127.0.0.1", [port, port + 1])
    assert res.target == "127.0.0.1"
    assert res.total == 2
    assert port in res.open_ports
    states = {r.port: r.state for r in res.results}
    assert states[port] == "open"
    assert states[port + 1] == "closed"
    srv.close()


# --------------------------------------------------------------------------
# CVE 查询
# --------------------------------------------------------------------------
def test_lookup_cve_hit():
    rows = sec.lookup_cve("smb")
    assert len(rows) >= 2
    assert all("smb" in str(r["product"]).lower() for r in rows)


def test_lookup_cve_miss():
    rows = sec.lookup_cve("nonexistent_product_xyz")
    assert rows == []


def test_lookup_cve_case_insensitive():
    assert len(sec.lookup_cve("LOG4J")) >= 1
