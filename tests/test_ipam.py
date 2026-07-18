"""core/ipam 纯函数单测（不依赖 GUI / 网络）。"""

import os

import pytest

from netops_studio.core.ipam import (
    IpamStore, allocate, detect_conflicts, reconcile, release, utilization,
)


@pytest.fixture
def store(tmp_path):
    path = os.path.join(str(tmp_path), "ipam.json")
    s = IpamStore(path)
    s.add_subnet("192.168.1.0/30")  # 2 个可用地址
    return s


def test_add_remove_subnet(tmp_path):
    s = IpamStore(os.path.join(str(tmp_path), "ipam.json"))
    s.add_subnet("10.0.0.0/29")
    assert s.has_subnet("10.0.0.0/29")
    # 重复添加应报错
    with pytest.raises(ValueError):
        s.add_subnet("10.0.0.0/29")
    s.remove_subnet("10.0.0.0/29")
    assert not s.has_subnet("10.0.0.0/29")
    with pytest.raises(ValueError):
        s.remove_subnet("10.0.0.0/29")


def test_allocate_release(store):
    ip1 = allocate(store, "192.168.1.0/30", "alice", "gw")
    ip2 = allocate(store, "192.168.1.0/30", "bob")
    assert ip1 == "192.168.1.1"
    assert ip2 == "192.168.1.2"
    # 同一子网内 IP 不重复
    assert ip1 != ip2
    # 已无空闲地址
    with pytest.raises(ValueError):
        allocate(store, "192.168.1.0/30", "carol")
    # 释放后可再次分配
    release(store, "192.168.1.0/30", ip1)
    ip3 = allocate(store, "192.168.1.0/30", "dave")
    assert ip3 == ip1
    # 释放不存在的 IP
    with pytest.raises(ValueError):
        release(store, "192.168.1.0/30", "192.168.1.9")


def test_allocate_unknown_subnet(store):
    with pytest.raises(ValueError):
        allocate(store, "172.16.0.0/24", "x")


def test_utilization(store):
    assert utilization("192.168.1.0/30", store) == 0.0
    allocate(store, "192.168.1.0/30", "a")
    # 1/2 = 50%
    assert utilization("192.168.1.0/30", store) == 50.0
    allocate(store, "192.168.1.0/30", "b")
    assert utilization("192.168.1.0/30", store) == 100.0
    # 未知子网
    with pytest.raises(ValueError):
        utilization("172.16.0.0/24", store)


def test_detect_conflicts(store):
    allocate(store, "192.168.1.0/30", "alice")  # 192.168.1.1 offline
    allocate(store, "192.168.1.0/30", "bob")    # 192.168.1.2 offline
    # 无发现数据时，两个已分配 IP 均 absent
    conflicts = detect_conflicts(store, [])
    assert len(conflicts) == 2
    assert all(c["reason"] == "absent_in_discovery" for c in conflicts)

    # 发现 192.168.1.1 在线（store 仍 offline，尚未对账 → 不算状态冲突），192.168.1.2 缺失
    conflicts = detect_conflicts(store, [
        {"ip": "192.168.1.1", "mac": "aa:bb:cc:00:00:01", "status": "online"},
    ])
    assert len(conflicts) == 1
    assert conflicts[0]["ip"] == "192.168.1.2"
    assert conflicts[0]["reason"] == "absent_in_discovery"

    # status 不符：手动将 192.168.1.1 标为 online，发现端却报 down（192.168.1.2 仍缺失）
    store.data["subnets"][0]["allocations"][0]["status"] = "online"
    conflicts = detect_conflicts(store, [{"ip": "192.168.1.1", "status": "down"}])
    reasons = {c["ip"]: c["reason"] for c in conflicts}
    assert reasons.get("192.168.1.1") == "status_mismatch"
    assert reasons.get("192.168.1.2") == "absent_in_discovery"

    # MAC 不符：记录 mac 与发现 mac 不同
    store.data["subnets"][0]["allocations"][0]["mac"] = "aa:aa:aa:aa:aa:aa"
    conflicts = detect_conflicts(store, [
        {"ip": "192.168.1.1", "mac": "bb:bb:bb:bb:bb:bb", "status": "online"},
    ])
    assert any(c["reason"] == "mac_mismatch" for c in conflicts)


def test_reconcile(store):
    allocate(store, "192.168.1.0/30", "alice")  # 192.168.1.1
    allocate(store, "192.168.1.0/30", "bob")    # 192.168.1.2
    # 仅发现 192.168.1.1
    summary = reconcile(store, [{"ip": "192.168.1.1", "status": "online"}])
    assert summary["online"] == 1
    assert summary["offline"] == 1
    assert summary["total"] == 2
    assert len(summary["changes"]) == 1  # 仅 192.168.1.1 由 offline→online

    # 全量发现后，192.168.1.2 也上线
    summary2 = reconcile(store, [
        {"ip": "192.168.1.1", "status": "online"},
        {"ip": "192.168.1.2", "status": "online"},
    ])
    assert summary2["online"] == 2
    assert summary2["offline"] == 0
    # 192.168.1.1 状态未变（仍 online），仅 192.168.1.2 由 offline→online
    assert len(summary2["changes"]) == 1

    # 发现报 down、且 192.168.1.2 不再出现 → 均判离线
    summary3 = reconcile(store, [{"ip": "192.168.1.1", "status": "down"}])
    assert summary3["online"] == 0
    assert summary3["offline"] == 2
    assert len(summary3["changes"]) == 2
