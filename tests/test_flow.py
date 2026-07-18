"""core/flow 纯函数单测（解析 / Top Talkers / 应用占比 / 异常检测）。"""

import netops_studio.core.flow as flow


SAMPLE_JSON = """
[
  {"srcaddr": "10.0.0.1", "dstaddr": "8.8.8.8", "srcport": 12345,
   "dstport": 443, "protocol": 6, "bytes": 5000, "packets": 10},
  {"srcaddr": "10.0.0.2", "dstaddr": "1.1.1.1", "srcport": 2222,
   "dstport": 53, "protocol": 17, "bytes": 300, "packets": 2},
  {"srcaddr": "10.0.0.1", "dstaddr": "9.9.9.9", "srcport": 3333,
   "dstport": 80, "protocol": 6, "bytes": 2000, "packets": 5}
]
"""

SAMPLE_CSV = """src,dst,src_port,dst_port,protocol,bytes,packets
10.0.0.1,8.8.8.8,12345,443,6,5000,10
10.0.0.2,1.1.1.1,2222,53,17,300,2
10.0.0.1,9.9.9.9,3333,80,6,2000,5
"""


def test_parse_netflow_json():
    recs = flow.parse_netflow_json(SAMPLE_JSON)
    assert len(recs) == 3
    assert isinstance(recs[0], flow.FlowRecord)
    # 协议数字应被标准化
    assert recs[0].protocol == "TCP"
    assert recs[1].protocol == "UDP"
    # 端口与字节
    assert recs[0].dst_port == 443 and recs[0].bytes == 5000
    assert recs[2].dst_port == 80


def test_parse_netflow_json_empty():
    assert flow.parse_netflow_json("") == []
    assert flow.parse_netflow_json("   ") == []


def test_parse_netflow_json_ipfix_wrapper():
    # 兼容被包裹的导出结构
    wrapped = '{"flows": ' + SAMPLE_JSON + '}'
    recs = flow.parse_netflow_json(wrapped)
    assert len(recs) == 3


def test_parse_netflow_json_bad():
    try:
        flow.parse_netflow_json("{not valid json")
    except ValueError:
        pass
    else:
        raise AssertionError("应抛出 ValueError")


def test_parse_flow_csv():
    recs = flow.parse_flow_csv(SAMPLE_CSV)
    assert len(recs) == 3
    assert recs[0].src == "10.0.0.1"
    assert recs[0].dst_port == 443
    assert recs[1].protocol == "UDP"
    assert recs[2].bytes == 2000


def test_top_talkers_sorted_and_limited():
    recs = flow.parse_netflow_json(SAMPLE_JSON)
    top = flow.top_talkers(recs)
    assert top[0].bytes == 5000
    assert top[1].bytes == 2000
    assert top[2].bytes == 300
    # 截断
    top2 = flow.top_talkers(recs, n=2)
    assert len(top2) == 2
    assert top2[0].bytes == 5000
    # 空列表安全
    assert flow.top_talkers([]) == []


def test_app_share():
    recs = flow.parse_netflow_json(SAMPLE_JSON)
    share = flow.app_share(recs)
    assert share["HTTPS"] == 5000
    assert share["DNS"] == 300
    assert share["HTTP"] == 2000
    # 总和一致
    assert sum(share.values()) == 7300
    # 降序
    vals = list(share.values())
    assert vals == sorted(vals, reverse=True)
    assert flow.app_share([]) == {}


def test_detect_anomalies_share():
    recs = flow.parse_netflow_json(SAMPLE_JSON)
    # 5000 / 7300 ≈ 68% > 50%，应被判为单流占比异常
    anomalies = flow.detect_anomalies(recs)
    types = [a["type"] for a in anomalies]
    assert "单流占比异常" in types
    # 默认阈值 100MB，本样例无单流超过，不应有“大流量单流”
    assert "大流量单流" not in types


def test_detect_anomalies_threshold():
    recs = flow.parse_netflow_json(SAMPLE_JSON)
    # 阈值设为 0.001 MB (=1000 字节)，5000 字节与 2000 字节均超过
    anomalies = flow.detect_anomalies(recs, threshold_mb=0.001)
    big = [a for a in anomalies if a["type"] == "大流量单流"]
    assert len(big) == 2
    assert all(a["bytes"] > 1000 for a in big)
    # 空列表安全
    assert flow.detect_anomalies([]) == []


def test_import_flow_json(tmp_path):
    p = tmp_path / "flows.json"
    p.write_text(SAMPLE_JSON, encoding="utf-8")
    recs = flow.import_flow(str(p))
    assert len(recs) == 3


def test_import_flow_csv(tmp_path):
    p = tmp_path / "flows.csv"
    p.write_text(SAMPLE_CSV, encoding="utf-8")
    recs = flow.import_flow(str(p))
    assert len(recs) == 3
