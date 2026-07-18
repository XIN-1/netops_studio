"""core/monitor 单测：阈值判定、syslog 解析、趋势统计、COMMON_OIDS。"""

import netops_studio.core.monitor as mon


def test_common_oids_nonempty():
    assert len(mon.COMMON_OIDS) > 0
    keys = {"name", "oid", "mib"}
    for item in mon.COMMON_OIDS:
        assert keys.issubset(item.keys())
    # 必含常见项
    oids = {i["oid"] for i in mon.COMMON_OIDS}
    assert "1.3.6.1.2.1.2.2.1.10" in oids   # ifInOctets
    assert "1.3.6.1.2.1.2.2.1.16" in oids   # ifOutOctets
    assert "1.3.6.1.2.1.1.3.0" in oids      # sysUpTime
    assert "1.3.6.1.2.1.1.1.0" in oids      # sysDescr
    assert any("hrSystem" in i["name"] for i in mon.COMMON_OIDS)


def _rule(op, value, sev="crit"):
    return mon.ThresholdRule(metric="m", op=op, value=value, severity=sev)


def test_evaluate_ops():
    # >
    assert mon.evaluate(10, _rule(">", 5)) == "crit"
    assert mon.evaluate(3, _rule(">", 5)) == "ok"
    # <
    assert mon.evaluate(2, _rule("<", 5)) == "crit"
    assert mon.evaluate(8, _rule("<", 5)) == "ok"
    # >=
    assert mon.evaluate(5, _rule(">=", 5)) == "crit"
    assert mon.evaluate(4, _rule(">=", 5)) == "ok"
    # <=
    assert mon.evaluate(5, _rule("<=", 5)) == "crit"
    assert mon.evaluate(6, _rule("<=", 5)) == "ok"
    # ==
    assert mon.evaluate(5, _rule("==", 5)) == "crit"
    assert mon.evaluate(6, _rule("==", 5)) == "ok"


def test_evaluate_severity_warn():
    assert mon.evaluate(99, _rule(">", 10, sev="warn")) == "warn"


def test_evaluate_bad_op():
    try:
        mon.evaluate(1, _rule("x", 1))
    except ValueError:
        pass
    else:
        raise AssertionError("非法 op 应抛 ValueError")


def test_parse_syslog_rfc3164():
    line = "<34>Oct 13 09:29:45 mymachine su: 'su root' failed for lonvick"
    p = mon.parse_syslog(line)
    assert p["facility"] == 4          # 34 // 8
    assert p["severity"] == 2         # 34 % 8
    assert p["host"] == "mymachine"
    assert "su root" in p["msg"]
    assert p["ts"].startswith("Oct 13")


def test_parse_syslog_rfc5424():
    line = "<165>1 2003-10-11T22:14:15.003Z myhost app 1234 ID47 - an event happened"
    p = mon.parse_syslog(line)
    assert p["facility"] == 20         # 165 // 8
    assert p["severity"] == 5          # 165 % 8
    assert p["host"] == "myhost"
    assert p["ts"].startswith("2003-10-11")
    assert p["msg"] == "an event happened"


def test_parse_syslog_no_pri():
    p = mon.parse_syslog("just some plain text")
    assert p["facility"] == -1
    assert p["severity"] == -1
    assert p["msg"] == "just some plain text"


def test_trend_stats():
    s = mon.trend_stats([1.0, 2.0, 3.0, 4.0])
    assert s["min"] == 1.0
    assert s["max"] == 4.0
    assert abs(s["avg"] - 2.5) < 1e-9


def test_trend_stats_empty():
    s = mon.trend_stats([])
    assert s["min"] is None and s["max"] is None and s["avg"] is None


def test_parse_trap_placeholder():
    text = (
        "enterprise: 1.3.6.1.4.1.8072\n"
        "agent: 10.0.0.1\n"
        "1.3.6.1.2.1.1.3.0 = 12345\n"
        "message: interface down"
    )
    t = mon.parse_trap(text)
    assert t["enterprise"] == "1.3.6.1.4.1.8072"
    assert t["agent"] == "10.0.0.1"
    assert len(t["oids"]) >= 1
    assert "interface down" in t["msg"]
