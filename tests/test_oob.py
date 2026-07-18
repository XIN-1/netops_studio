"""core/outofband 单测：解析逻辑（纯函数）+ RackStore 持久化（本地临时文件）。"""

import json

import pytest

import netops_studio.core.outofband as oob


# --------------------------------------------------------------------------
# parse_redfish
# --------------------------------------------------------------------------
def test_parse_redfish_sample():
    sample = json.dumps({
        "Id": "1",
        "Status": {"Health": "OK", "State": "Enabled"},
        "Thermal": {
            "Temperatures": [
                {"Name": "Inlet", "ReadingCelsius": 22.0},
                {"Name": "CPU1", "ReadingCelsius": 55.5},
            ]
        },
        "Power": {
            "PowerControl": [
                {"Name": "System", "PowerConsumedWatts": 350.0},
                {"Name": "Chassis", "PowerConsumedWatts": 120.0},
            ]
        },
    })
    res = oob.parse_redfish(sample)
    assert res["health"] == "OK"
    assert res["temp"] == {"Inlet": 22.0, "CPU1": 55.5}
    assert res["power"] == {"System": 350.0, "Chassis": 120.0}


def test_parse_redfish_missing_fields():
    res = oob.parse_redfish(json.dumps({"Id": "1"}))
    assert res["health"] == "Unknown"
    assert res["temp"] == {}
    assert res["power"] == {}


def test_parse_redfish_invalid_json():
    res = oob.parse_redfish("not json at all")
    assert res["health"] == "Unknown"
    assert res["temp"] == {}
    assert res["power"] == {}


# --------------------------------------------------------------------------
# parse_ipmitool
# --------------------------------------------------------------------------
def test_parse_ipmitool_sample():
    text = (
        "CPU Temp        | 45.000     | degrees C  | ok\n"
        "System Temp     | 22.000     | degrees C  | ok\n"
        "Fan1            | 4500.000   | RPM        | ok\n"
        "Vcore           | 1.200      | Volts      | ok\n"
    )
    res = oob.parse_ipmitool(text)
    assert res["CPU Temp"] == 45.0
    assert res["System Temp"] == 22.0
    assert res["Fan1"] == 4500.0
    assert res["Vcore"] == 1.2
    assert len(res) == 4


def test_parse_ipmitool_non_numeric():
    text = "Status LED      | present    | discrete   | ok\n"
    res = oob.parse_ipmitool(text)
    assert res["Status LED"] == "present"


def test_parse_ipmitool_skips_garbage():
    text = "this line has no pipe\n\n   \nSensorA | 1.0 | C | ok\n"
    res = oob.parse_ipmitool(text)
    assert res == {"SensorA": 1.0}


# --------------------------------------------------------------------------
# parse_env
# --------------------------------------------------------------------------
def test_parse_env_labeled():
    text = "温度: 22.5\n湿度: 55\n"
    res = oob.parse_env(text)
    assert res == {"temp": 22.5, "humidity": 55.0}


def test_parse_env_english():
    text = "Temp: 19.0\nHumidity: 60%\n"
    res = oob.parse_env(text)
    assert res == {"temp": 19.0, "humidity": 60.0}


def test_parse_env_from_ipmitool():
    text = (
        "Inlet Temp     | 21.000    | degrees C  | ok\n"
        "Humidity       | 48.000    | percent    | ok\n"
    )
    res = oob.parse_env(text)
    assert res["temp"] == 21.0
    assert res["humidity"] == 48.0


def test_parse_env_empty():
    assert oob.parse_env("no temperature here") == {}


# --------------------------------------------------------------------------
# RackStore（本地临时文件）
# --------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    return oob.RackStore(path=str(tmp_path / "racks.json"))


def test_rackstore_add_and_persist(store):
    assert store.add_rack("RACK-A") is True
    assert store.add_rack("RACK-A") is False  # 重复忽略
    assert store.add_device("RACK-A", 10, "core-sw1", "SN1") is True
    assert store.add_device("RACK-A", 11, "core-sw2", "SN2") is True
    assert store.add_device("NOPE", 1, "x") is False  # 机架不存在

    # 重新加载应保留数据
    reloaded = oob.RackStore(path=store.path)
    assert "RACK-A" in reloaded.list_racks()
    rack = reloaded.get_rack("RACK-A")
    assert len(rack["devices"]) == 2
    assert rack["devices"][0]["sn"] == "SN1"


def test_rackstore_remove(store):
    store.add_rack("RACK-A")
    store.add_device("RACK-A", 10, "core-sw1", "SN1")
    assert store.remove_device("RACK-A", "core-sw1") is True
    assert store.remove_device("RACK-A", "core-sw1") is False  # 已无
    assert store.remove_rack("RACK-A") is True
    assert store.remove_rack("RACK-A") is False  # 已无
    assert store.get_rack("RACK-A") is None


def test_rackstore_save_format(store, tmp_path):
    store.add_rack("RACK-B")
    store.add_device("RACK-B", 5, "fw1", "SNX")
    raw = (tmp_path / "racks.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data[0]["name"] == "RACK-B"
    assert data[0]["devices"][0]["u"] == 5
