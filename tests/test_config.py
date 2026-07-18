"""core/config_mgmt 单测（仅本模块，独立运行）。"""

import os
import tempfile

import pytest

from netops_studio.core import config_mgmt


# --------------------------------------------------------------------------
# encrypt_bytes / decrypt_bytes 往返
# --------------------------------------------------------------------------
def test_encrypt_decrypt_roundtrip():
    key = os.urandom(32)
    plain = b"super-secret-running-config"
    ct = config_mgmt.encrypt_bytes(plain, key)
    assert ct != plain
    assert config_mgmt.decrypt_bytes(ct, key) == plain


def test_encrypt_key_length_guard():
    with pytest.raises(ValueError):
        config_mgmt.encrypt_bytes(b"x", b"tooshort")


# --------------------------------------------------------------------------
# diff_configs
# --------------------------------------------------------------------------
def test_diff_configs_detects_change():
    a = "interface GigabitEthernet0/1\n ip address 10.0.0.1 255.255.255.0\n"
    b = "interface GigabitEthernet0/1\n ip address 10.0.0.2 255.255.255.0\n"
    diff = config_mgmt.diff_configs(a, b)
    assert "10.0.0.2" in diff
    assert "- ip address 10.0.0.1" in diff
    assert "+ ip address 10.0.0.2" in diff


def test_diff_configs_identical():
    a = "line vty 0 4\n login\n"
    assert config_mgmt.diff_configs(a, a) == ""


# --------------------------------------------------------------------------
# check_baseline
# --------------------------------------------------------------------------
def test_check_baseline_forbidden_hit():
    rules = [{"name": "no telnet", "pattern": r"transport input telnet", "forbidden": True}]
    v = config_mgmt.check_baseline("line vty 0 4\ntransport input telnet\n", rules)
    assert len(v) == 1
    assert v[0]["line"] == 2


def test_check_baseline_forbidden_miss():
    rules = [{"name": "no telnet", "pattern": r"transport input telnet", "forbidden": True}]
    assert config_mgmt.check_baseline("line vty 0 4\ntransport input ssh\n", rules) == []


def test_check_baseline_required_missing():
    rules = [{"name": "need ntp", "pattern": r"ntp server", "forbidden": False}]
    v = config_mgmt.check_baseline("hostname sw1\n", rules)
    assert len(v) == 1
    assert "缺少" in v[0]["detail"]


def test_check_baseline_required_present():
    rules = [{"name": "need ntp", "pattern": r"ntp server", "forbidden": False}]
    assert config_mgmt.check_baseline("ntp server 10.0.0.1\n", rules) == []


# --------------------------------------------------------------------------
# CredentialVault 往返（临时 key 文件）
# --------------------------------------------------------------------------
def test_credential_vault_roundtrip(tmp_path):
    key_file = str(tmp_path / ".crypto_key")
    vault = config_mgmt.CredentialVault(key_path=key_file)
    vault.add_credential("dev1", "admin", "S3cret!")
    assert "dev1" in vault.list_names()
    user, pw = vault.get_credential("dev1")
    assert user == "admin"
    assert pw == "S3cret!"


def test_credential_vault_persist_across_instances(tmp_path):
    key_file = str(tmp_path / ".crypto_key")
    v1 = config_mgmt.CredentialVault(key_path=key_file)
    v1.add_credential("dev2", "root", "pw")
    v2 = config_mgmt.CredentialVault(key_path=key_file)
    assert v2.get_credential("dev2") == ("root", "pw")


def test_credential_vault_delete(tmp_path):
    key_file = str(tmp_path / ".crypto_key")
    vault = config_mgmt.CredentialVault(key_path=key_file)
    vault.add_credential("tmp", "u", "p")
    vault.delete("tmp")
    assert "tmp" not in vault.list_names()
    with pytest.raises(KeyError):
        vault.get_credential("tmp")


def test_credential_vault_key_is_32_bytes_on_create(tmp_path):
    key_file = str(tmp_path / ".crypto_key")
    vault = config_mgmt.CredentialVault(key_path=key_file)
    assert os.path.isfile(key_file)
    assert os.path.getsize(key_file) == 32


# --------------------------------------------------------------------------
# 备份库 / 模板（临时 DATA_DIR 通过 monkeypatch）
# --------------------------------------------------------------------------
@pytest.fixture
def isolated_data(monkeypatch, tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(config_mgmt, "DATA_DIR", str(d))
    monkeypatch.setattr(config_mgmt, "KEY_PATH", str(d / ".crypto_key"))
    monkeypatch.setattr(config_mgmt, "CRED_FILE", str(d / "credentials.json"))
    monkeypatch.setattr(config_mgmt, "CONFIGS_DIR", str(d / "configs"))
    monkeypatch.setattr(config_mgmt, "TEMPLATES_DIR", str(d / "templates"))
    return d


def test_backup_and_rollback(isolated_data):
    ts = config_mgmt.backup_config("sw1", "hostname sw1\n")
    assert ts in config_mgmt.list_backups("sw1")
    assert config_mgmt.get_backup("sw1", ts) == "hostname sw1\n"
    assert config_mgmt.rollback("sw1", ts) == "hostname sw1\n"


def test_backup_prune_keep(isolated_data, monkeypatch):
    counter = {"n": 0}

    def fake_strftime(fmt):
        counter["n"] += 1
        return f"20260101_{counter['n']:06d}"

    monkeypatch.setattr(config_mgmt.time, "strftime", fake_strftime)
    for i in range(15):
        config_mgmt.backup_config("sw2", f"cfg {i}\n", keep=5)
    assert len(config_mgmt.list_backups("sw2")) == 5


def test_render_template(isolated_data):
    out = config_mgmt.render_template("sample", {
        "device_name": "sw1", "mgmt_ip": "10.0.0.1", "vendor": "cisco",
        "loopback_ip": "1.1.1.1", "snmp_ro": "public", "syslog_server": "10.0.0.9",
        "ntp_server": "10.0.0.10",
    })
    assert "name: sw1" in out
    assert "ip address 1.1.1.1 255.255.255.255" in out
    assert "$" not in out


def test_device_type_mapping():
    assert config_mgmt._resolve_device_type("cisco") == "cisco_ios"
    assert config_mgmt._resolve_device_type("huawei") == "huawei_vrp"
    assert config_mgmt._resolve_device_type("h3c") == "hp_comware"
    assert config_mgmt._resolve_device_type("juniper") == "juniper_junos"
    with pytest.raises(ValueError):
        config_mgmt._resolve_device_type("unknown")
