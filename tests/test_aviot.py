"""core/av_iot 单测：estimate_mos / parse_sdp / parse_probe。"""

import netops_studio.core.av_iot as av


# --------------------------------------------------------------------------
# estimate_mos（简化 E-model）
# --------------------------------------------------------------------------
def test_estimate_mos_perfect():
    # 无丢包无抖动：接近满分的 MOS
    mos = av.estimate_mos(0.0, 0.0)
    assert 4.0 <= mos <= 4.5


def test_estimate_mos_loss_degrades():
    good = av.estimate_mos(0.0, 0.0)
    bad = av.estimate_mos(20.0, 0.0)
    assert bad < good


def test_estimate_mos_jitter_degrades():
    good = av.estimate_mos(0.0, 0.0)
    bad = av.estimate_mos(0.0, 100.0)
    assert bad < good


def test_estimate_mos_clamped():
    # 极端损伤不应产生无意义的 MOS
    mos = av.estimate_mos(100.0, 1000.0)
    assert 1.0 <= mos <= 4.5


def test_estimate_mos_monotonic_loss():
    m1 = av.estimate_mos(1.0, 0.0)
    m5 = av.estimate_mos(5.0, 0.0)
    m20 = av.estimate_mos(20.0, 0.0)
    assert m1 >= m5 >= m20


# --------------------------------------------------------------------------
# parse_sdp
# --------------------------------------------------------------------------
SAMPLE_SDP = """
v=0
o=- 1400861751 1 IN IP4 192.168.1.64
s=Session streamed with GStreamer
i=rtsp-server
t=0 0
a=tool:GStreamer
a=type:broadcast
a=range:npt=now-
a=control:rtsp://192.168.1.64:554/stream1
m=video 0 RTP/AVP 96
c=IN IP4 239.0.0.1/1
a=rtpmap:96 H264/90000
a=fmtp:96 packetization-mode=1
a=control:streamid=0
m=audio 0 RTP/AVP 97
c=IN IP4 239.0.0.1/1
a=rtpmap:97 PCMU/8000
a=control:streamid=1
"""


def test_parse_sdp_two_tracks():
    tracks = av.parse_sdp(SAMPLE_SDP)
    assert len(tracks) == 2


def test_parse_sdp_video_track():
    tracks = av.parse_sdp(SAMPLE_SDP)
    video = next(t for t in tracks if t.media == "video")
    assert video.codec == "H264"
    assert video.clock_rate == 90000
    assert video.payload_type == "96"
    assert video.control == "streamid=0"


def test_parse_sdp_audio_track():
    tracks = av.parse_sdp(SAMPLE_SDP)
    audio = next(t for t in tracks if t.media == "audio")
    assert audio.codec == "PCMU"
    assert audio.clock_rate == 8000


def test_parse_sdp_empty():
    assert av.parse_sdp("") == []


# --------------------------------------------------------------------------
# parse_probe（WS-Discovery ProbeMatch 应答）
# --------------------------------------------------------------------------
SAMPLE_PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"
  xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
  xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery">
  <soap:Header>
    <wsa:MessageID>urn:uuid:reply-0001</wsa:MessageID>
    <wsa:RelatesTo>urn:uuid:req-0001</wsa:RelatesTo>
    <wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
    <wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatch</wsa:Action>
  </soap:Header>
  <soap:Body>
    <wsd:ProbeMatch>
      <wsd:EndpointReference>
        <wsa:Address>urn:uuid:device-camera-01</wsa:Address>
      </wsd:EndpointReference>
      <wsd:Types>wsd:NetworkVideoTransmitter</wsd:Types>
      <wsd:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/hardware/HIK</wsd:Scopes>
      <wsd:XAddrs>http://192.168.1.64/onvif/device_service</wsd:XAddrs>
      <wsd:MetadataVersion>1</wsd:MetadataVersion>
    </wsd:ProbeMatch>
  </soap:Body>
</soap:Envelope>"""


def test_parse_probe_single():
    devices = av.parse_probe(SAMPLE_PROBE)
    assert len(devices) == 1


def test_parse_probe_fields():
    dev = av.parse_probe(SAMPLE_PROBE)[0]
    assert dev.endpoint == "urn:uuid:device-camera-01"
    assert dev.types == "wsd:NetworkVideoTransmitter"
    assert "http://192.168.1.64/onvif/device_service" in dev.xaddrs
    assert any("type/video_encoder" in s for s in dev.scopes)
    assert dev.metadata_version == "1"


def test_parse_probe_empty():
    assert av.parse_probe("") == []
    assert av.parse_probe("<not-xml") == []


def test_build_probe_well_formed():
    probe = av.build_probe()
    # 生成的 Probe 报文本身应可被 XML 解析
    import xml.etree.ElementTree as ET

    root = ET.fromstring(probe)
    # 含 Probe 动作
    assert "Probe" in probe
    assert root is not None
