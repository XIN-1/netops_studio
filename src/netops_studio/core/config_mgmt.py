"""配置管理引擎（core/config_mgmt.py）。

涵盖：凭据保险箱（AES）、配置备份库、合规基线、模板库、设备连接。
纯 Python 引擎层，禁止 import PySide6/Qt。重依赖（cryptography / yaml /
netmiko）均惰性导入。返回 dict / list / 结构化结果，由 gui 渲染。
"""

from __future__ import annotations

import base64
import difflib
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "..", "data")
KEY_PATH = os.path.join(DATA_DIR, ".crypto_key")
CRED_FILE = os.path.join(DATA_DIR, "credentials.json")
CONFIGS_DIR = os.path.join(DATA_DIR, "configs")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")

DEFAULT_KEEP = 10

# 多厂商 device_type 映射（netmiko）
VENDOR_DEVICE_TYPE = {
    "cisco": "cisco_ios",
    "huawei": "huawei_vrp",
    "h3c": "hp_comware",
    "juniper": "juniper_junos",
}


# --------------------------------------------------------------------------
# 纯函数：字节级 AES（Fernet = AES-128-CBC + HMAC）
# --------------------------------------------------------------------------
def _fernet(key: bytes):
    from cryptography.fernet import Fernet

    if len(key) != 32:
        raise ValueError("密钥必须为 32 字节（os.urandom(32) 生成）")
    # Fernet 要求密钥为 urlsafe-base64 编码的 32 字节（44 字符），
    # 这里把裸 32 字节密钥重新编码后喂给 Fernet。
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_bytes(plaintext: bytes, key: bytes) -> bytes:
    """用 key（32 字节裸密钥）加密 plaintext，返回密文字节。"""
    return _fernet(key).encrypt(plaintext)


def decrypt_bytes(ciphertext: bytes, key: bytes) -> bytes:
    """解密 encrypt_bytes 产生的密文，返回明文字节。"""
    return _fernet(key).decrypt(ciphertext)


# --------------------------------------------------------------------------
# 凭据保险箱
# --------------------------------------------------------------------------
class CredentialVault:
    """基于 cryptography 的 AES 凭据保险箱。密钥存于 key_path。

    存储结构：{name: {user, password(加密b64)}}。password 字段在落盘时加密。
    """

    def __init__(self, key_path: Optional[str] = None) -> None:
        self.key_path = key_path or KEY_PATH
        os.makedirs(os.path.dirname(self.key_path), exist_ok=True)
        self._key = self._load_or_create_key()

    # -- 密钥 --
    def _load_or_create_key(self) -> bytes:
        if os.path.isfile(self.key_path):
            with open(self.key_path, "rb") as f:
                key = f.read()
            if len(key) != 32:
                raise ValueError(f"密钥文件长度异常（应 32 字节）：{self.key_path}")
            return key
        key = os.urandom(32)
        with open(self.key_path, "wb") as f:
            f.write(key)
        os.chmod(self.key_path, 0o600)
        return key

    def rotate_key(self) -> None:
        """重新生成密钥并重新加密全部凭据。"""
        new_key = os.urandom(32)
        # 先解密所有现有凭据
        store = self._read_store()
        self._key = new_key
        with open(self.key_path, "wb") as f:
            f.write(new_key)
        os.chmod(self.key_path, 0o600)
        self._write_store(store)

    # -- 内部存储 --
    def _read_store(self) -> Dict[str, dict]:
        if not os.path.isfile(CRED_FILE):
            return {}
        try:
            with open(CRED_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        # 解密 password 字段
        out: Dict[str, dict] = {}
        for name, rec in raw.items():
            pw = rec.get("password", "")
            if pw:
                try:
                    pw = decrypt_bytes(base64.b64decode(pw), self._key).decode("utf-8")
                except Exception:  # noqa: BLE001
                    pw = ""
            out[name] = {"user": rec.get("user", ""), "password": pw}
        return out

    def _write_store(self, store: Dict[str, dict]) -> None:
        os.makedirs(os.path.dirname(CRED_FILE), exist_ok=True)
        raw: Dict[str, dict] = {}
        for name, rec in store.items():
            enc_pw = base64.b64encode(
                encrypt_bytes(rec.get("password", "").encode("utf-8"), self._key)
            ).decode("ascii")
            raw[name] = {"user": rec.get("user", ""), "password": enc_pw}
        with open(CRED_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)

    # -- 公共 API --
    def add_credential(self, name: str, user: str, password: str) -> None:
        store = self._read_store()
        store[name] = {"user": user, "password": password}
        self._write_store(store)

    def get_credential(self, name: str):
        store = self._read_store()
        rec = store.get(name)
        if not rec:
            raise KeyError(f"凭据不存在：{name}")
        return (rec["user"], rec["password"])

    def list_names(self) -> List[str]:
        return sorted(self._read_store().keys())

    def delete(self, name: str) -> None:
        store = self._read_store()
        if name not in store:
            raise KeyError(f"凭据不存在：{name}")
        del store[name]
        self._write_store(store)


# --------------------------------------------------------------------------
# 配置备份库（带时间戳历史）
# --------------------------------------------------------------------------
def backup_config(device: str, content: str, keep: int = DEFAULT_KEEP) -> str:
    """保存一份带时间戳的备份，保留最近 keep 份。返回时间戳字符串。"""
    device_dir = os.path.join(CONFIGS_DIR, _safe(device))
    os.makedirs(device_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(device_dir, f"{ts}.cfg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    _prune(device, keep)
    return ts


def list_backups(device: str) -> List[str]:
    device_dir = os.path.join(CONFIGS_DIR, _safe(device))
    if not os.path.isdir(device_dir):
        return []
    files = [f for f in os.listdir(device_dir) if f.endswith(".cfg")]
    return sorted(f[:-4] for f in files)


def get_backup(device: str, ts: str) -> str:
    path = os.path.join(CONFIGS_DIR, _safe(device), f"{_safe(ts)}.cfg")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"备份不存在：{device} @ {ts}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def rollback(device: str, ts: str) -> str:
    """回滚到指定时间戳配置，返回其内容。"""
    return get_backup(device, ts)


def diff_configs(a: str, b: str) -> str:
    """用 unified_diff 生成两段配置的差异（a=旧，b=新）。"""
    a_lines = a.splitlines(keepends=True)
    b_lines = b.splitlines(keepends=True)
    diff = difflib.unified_diff(
        a_lines, b_lines, fromfile="current", tofile="incoming", lineterm=""
    )
    return "".join(diff)


def _prune(device: str, keep: int) -> None:
    device_dir = os.path.join(CONFIGS_DIR, _safe(device))
    if not os.path.isdir(device_dir):
        return
    files = sorted(f for f in os.listdir(device_dir) if f.endswith(".cfg"))
    excess = files[:-keep] if keep > 0 else files
    for f in excess:
        try:
            os.remove(os.path.join(device_dir, f))
        except OSError:
            pass


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


# --------------------------------------------------------------------------
# 合规基线
# --------------------------------------------------------------------------
@dataclass
class BaselineViolation:
    rule: str
    name: str
    detail: str
    line: Optional[int] = None


def check_baseline(config_text: str, rules: List[dict]) -> List[dict]:
    """检查配置文本是否违反基线规则。

    每条 rule:
      - name: 规则名
      - pattern: 正则（str）
      - forbidden: bool（默认 False）
        * forbidden=True  -> 任意一行匹配即违规（不应出现）
        * forbidden=False -> 没有任何行匹配即违规（必须存在）

    返回违规列表（dict），元素含 rule/name/detail/line。
    """
    lines = config_text.splitlines()
    violations: List[dict] = []
    for rule in rules:
        rname = rule.get("name", "")
        pattern = rule.get("pattern", "")
        forbidden = bool(rule.get("forbidden", False))
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            violations.append({
                "rule": rname, "name": rname,
                "detail": f"正则编译失败：{exc}", "line": None,
            })
            continue
        matched_lines = [i + 1 for i, ln in enumerate(lines) if rx.search(ln)]
        if forbidden:
            for ln in matched_lines:
                violations.append({
                    "rule": rname, "name": rname,
                    "detail": f"出现禁止内容（匹配 /{pattern}/）", "line": ln,
                })
        else:
            if not matched_lines:
                violations.append({
                    "rule": rname, "name": rname,
                    "detail": f"缺少必需配置（未匹配 /{pattern}/）", "line": None,
                })
    return violations


def default_baseline_rules() -> List[dict]:
    """返回一份示例合规基线（纯函数，可在此扩展）。"""
    return [
        {"name": "禁止明文 enable 密码", "pattern": r"enable password", "forbidden": True},
        {"name": "禁止 Telnet 服务", "pattern": r"transport input telnet", "forbidden": True},
        {"name": "必须配置 NTP", "pattern": r"ntp server", "forbidden": False},
        {"name": "必须配置 SNMP 团体", "pattern": r"snmp-server community", "forbidden": False},
        {"name": "必须关闭未用端口", "pattern": r"shutdown", "forbidden": False},
    ]


# --------------------------------------------------------------------------
# 模板库
# --------------------------------------------------------------------------
def _ensure_sample_template() -> None:
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    sample = os.path.join(TEMPLATES_DIR, "sample.yaml")
    if os.path.isfile(sample):
        return
    content = (
        "# NetOps Studio 示例模板\n"
        "device:\n"
        "  name: $device_name\n"
        "  mgmt_ip: $mgmt_ip\n"
        "  vendor: $vendor\n"
        "interface Loopback0\n"
        "  ip address $loopback_ip 255.255.255.255\n"
        "snmp-server community $snmp_ro RO\n"
        "logging host $syslog_server\n"
        "ntp server $ntp_server\n"
    )
    with open(sample, "w", encoding="utf-8") as f:
        f.write(content)


def render_template(name: str, vars: Dict[str, str]) -> str:
    """读取 data/templates/<name>.yaml 并用 vars 渲染 $占位符。

    使用 string.Template（避免与 YAML 自身的 {} 冲突）。
    """
    from string import Template

    _ensure_sample_template()
    path = os.path.join(TEMPLATES_DIR, f"{name}.yaml")
    if not os.path.isfile(path):
        raise FileNotFoundError(f"模板不存在：{name}（期望 {path}）")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        return Template(text).safe_substitute(vars)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"模板渲染失败：{exc}") from exc


# --------------------------------------------------------------------------
# 设备连接（netmiko 惰性导入）
# --------------------------------------------------------------------------
def _resolve_device_type(vendor: str) -> str:
    v = (vendor or "").lower()
    if v not in VENDOR_DEVICE_TYPE:
        raise ValueError(
            f"不支持的厂商：{vendor}（可选：{', '.join(VENDOR_DEVICE_TYPE)}）"
        )
    return VENDOR_DEVICE_TYPE[v]


def connect_and_backup(device: str, creds: dict, keep: int = DEFAULT_KEEP) -> dict:
    """连接设备并备份当前运行配置到本地库。creds 含 host/username/password/vendor。"""
    try:
        from netmiko import ConnectHandler
    except ImportError:
        raise RuntimeError(
            "缺少 netmiko，请先 `pip install netmiko` 后再执行设备连接类操作"
        )
    device_type = _resolve_device_type(creds.get("vendor", ""))
    conn = ConnectHandler(
        device_type=device_type,
        host=creds.get("host", ""),
        username=creds.get("username", ""),
        password=creds.get("password", ""),
        secret=creds.get("secret", ""),
    )
    try:
        conn.enable()
        output = conn.send_command("show running-config")
    finally:
        conn.disconnect()
    ts = backup_config(device, output, keep=keep)
    return {
        "device": device,
        "timestamp": ts,
        "vendor": creds.get("vendor", ""),
        "running_config": output,
        "backup_path": os.path.join(CONFIGS_DIR, _safe(device), f"{ts}.cfg"),
    }


def push_config(device: str, creds: dict, content: str) -> dict:
    """把配置文本下发到设备。content 为配置行集合（自动按行拆分）。"""
    try:
        from netmiko import ConnectHandler
    except ImportError:
        raise RuntimeError(
            "缺少 netmiko，请先 `pip install netmiko` 后再执行设备连接类操作"
        )
    device_type = _resolve_device_type(creds.get("vendor", ""))
    conn = ConnectHandler(
        device_type=device_type,
        host=creds.get("host", ""),
        username=creds.get("username", ""),
        password=creds.get("password", ""),
        secret=creds.get("secret", ""),
    )
    try:
        conn.enable()
        cmds = [ln.strip() for ln in content.splitlines() if ln.strip()]
        result = conn.send_config_set(cmds)
    finally:
        conn.disconnect()
    return {
        "device": device,
        "vendor": creds.get("vendor", ""),
        "commands": cmds,
        "output": result,
    }


# --------------------------------------------------------------------------
# 便捷：从保险箱取出凭据并组装连接 dict
# --------------------------------------------------------------------------
def creds_from_vault(vault: "CredentialVault", name: str, host: str,
                     vendor: str, secret: str = "") -> dict:
    user, password = vault.get_credential(name)
    return {
        "host": host,
        "username": user,
        "password": password,
        "vendor": vendor,
        "secret": secret,
    }
