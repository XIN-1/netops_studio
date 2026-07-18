"""core/rbac 单测（仅本模块，独立运行）。

覆盖：check_permission、record+load 审计、search_actions、plugin 扫描。
路径相关测试全部隔离到 tmp_path，不触碰仓库 data 目录。
"""

import json
import os

import pytest

from netops_studio.core import rbac
from netops_studio.core.rbac import AuditLog, DashboardConfig, User


# --------------------------------------------------------------------------
# check_permission
# --------------------------------------------------------------------------
def test_admin_has_wildcard():
    assert rbac.check_permission("admin", "anything.run") is True
    assert rbac.check_permission("admin", "discovery.run") is True


def test_operator_granted_and_denied():
    assert rbac.check_permission("operator", "discovery.run") is True
    assert rbac.check_permission("operator", "config.push") is True
    # operator 无用户管理类权限
    assert rbac.check_permission("operator", "user.create") is False


def test_viewer_only_view():
    assert rbac.check_permission("viewer", "discovery.view") is True
    assert rbac.check_permission("viewer", "discovery.run") is False
    assert rbac.check_permission("viewer", "config.push") is False


def test_unknown_role_denied():
    assert rbac.check_permission("ghost", "discovery.run") is False


def test_permission_matches_role_definition():
    for role, perms in rbac.ROLES.items():
        for action in perms:
            if action == "*":
                continue
            assert rbac.check_permission(role, action) is True


# --------------------------------------------------------------------------
# AuditLog record + load
# --------------------------------------------------------------------------
def test_audit_record_and_load(tmp_path):
    path = str(tmp_path / "audit.json")
    log = AuditLog(path=path)
    assert log.load() == []
    user = User("alice", "admin")
    entry = log.record(user, "config.push", "备份 core-sw1")
    assert entry["user"] == "alice"
    assert entry["role"] == "admin"
    assert entry["action"] == "config.push"
    assert entry["detail"] == "备份 core-sw1"
    assert "ts" in entry

    loaded = log.load()
    assert len(loaded) == 1
    assert loaded[0]["action"] == "config.push"


def test_audit_record_string_user(tmp_path):
    log = AuditLog(path=str(tmp_path / "audit.json"))
    log.record("bob", "audit.view", "查看审计")
    loaded = log.load()
    assert loaded[0]["user"] == "bob"
    assert loaded[0]["role"] == ""


def test_audit_search(tmp_path):
    log = AuditLog(path=str(tmp_path / "audit.json"))
    log.record(User("alice", "admin"), "config.push", "备份 core-sw1")
    log.record(User("carol", "viewer"), "audit.view", "查看日志")
    # 空查询返回全部
    assert len(log.search("")) == 2
    # 按 action 匹配
    assert len(log.search("config.push")) == 1
    # 按 user 匹配
    assert len(log.search("carol")) == 1
    # 按 detail 匹配
    assert len(log.search("core-sw1")) == 1
    # 无匹配
    assert log.search("nope") == []


def test_audit_persist_across_instances(tmp_path):
    p = str(tmp_path / "audit.json")
    AuditLog(path=p).record(User("a", "admin"), "x", "y")
    assert len(AuditLog(path=p).load()) == 1


# --------------------------------------------------------------------------
# search_actions
# --------------------------------------------------------------------------
def test_search_actions_empty_returns_all():
    all_actions = rbac.search_actions("")
    assert all_actions == sorted(rbac.ACTIONS.keys())


def test_search_actions_by_name():
    res = rbac.search_actions("ping")
    assert "diagnostics.ping" in res
    assert "discovery.scan" not in res


def test_search_actions_by_description():
    # "配置" 命中 config.backup / config.push 的描述
    res = rbac.search_actions("配置")
    assert "config.backup" in res
    assert "config.push" in res


def test_search_actions_pure_and_case_insensitive():
    a = rbac.search_actions("SCAN")
    b = rbac.search_actions("scan")
    assert a == b
    assert "discovery.scan" in a


# --------------------------------------------------------------------------
# 插件扫描
# --------------------------------------------------------------------------
def test_scan_plugins_empty_dir(tmp_path):
    d = tmp_path / "plugins"
    d.mkdir()
    assert rbac.scan_plugins(dir=str(d)) == []


def test_scan_plugins(tmp_path):
    d = tmp_path / "plugins"
    d.mkdir()
    p1 = d / "hello_alert"
    p1.mkdir()
    (p1 / "metadata.json").write_text(
        json.dumps({"id": "hello_alert", "name": "告警通知",
                    "version": "1.0.0", "description": "demo"}), encoding="utf-8"
    )
    p2 = d / "netbox_sync"
    p2.mkdir()
    (p2 / "metadata.json").write_text(
        json.dumps({"name": "NetBox 同步", "version": "0.9.0",
                    "description": "sync"}), encoding="utf-8"
    )
    # 缺少 metadata.json 的子目录应被忽略
    (d / "broken").mkdir()

    plugins = rbac.scan_plugins(dir=str(d))
    assert len(plugins) == 2
    ids = {p["id"] for p in plugins}
    assert ids == {"hello_alert", "netbox_sync"}
    # netbox_sync 未自带 id，应回退为目录名
    nb = next(p for p in plugins if p["name"] == "NetBox 同步")
    assert nb["id"] == "netbox_sync"


def test_scan_plugins_missing_dir(tmp_path):
    assert rbac.scan_plugins(dir=str(tmp_path / "nope")) == []


# --------------------------------------------------------------------------
# DashboardConfig save / load
# --------------------------------------------------------------------------
def test_dashboard_default_when_missing(tmp_path):
    cfg = DashboardConfig(path=str(tmp_path / "dashboard.json")).load()
    assert cfg == dict(rbac.DEFAULT_DASHBOARD)


def test_dashboard_save_load_roundtrip(tmp_path):
    path = str(tmp_path / "dashboard.json")
    dc = DashboardConfig(path=path)
    states = {"online": False, "latency": True, "throughput": False, "alerts": True}
    dc.save(states)
    loaded = dc.load()
    assert loaded == states


def test_dashboard_load_merges_unknown_keys(tmp_path):
    path = str(tmp_path / "dashboard.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"online": False, "extra": True}, f)
    loaded = DashboardConfig(path=path).load()
    assert loaded["online"] is False
    assert "extra" in loaded
    # 未提供的默认 KPI 仍保留默认 True
    assert loaded["latency"] is True
