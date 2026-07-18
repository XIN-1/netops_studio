"""国际化（app/i18n.py）。

zh_CN / en_US 资源加载，tr(key) 取词。纯 Python。
参考文档 §7。内置默认词表，亦可在 resources/locales 放 JSON 扩展。
"""

from __future__ import annotations

import json
import os
from typing import Dict

_DEFAULTS: Dict[str, Dict[str, str]] = {
    "zh_CN": {
        "app.title": "NetOps Studio 网维工作台",
        "nav.dashboard": "仪表盘",
        "nav.discovery": "资产与发现",
        "nav.diagnostics": "连通性诊断",
        "nav.speedtest": "性能与测速",
        "nav.subnet": "子网计算器",
        "nav.codec": "编解码工具",
        "action.run": "运行",
        "action.stop": "停止",
        "action.clear": "清空",
        "status.ready": "就绪",
        "common.online": "在线",
        "common.offline": "离线",
    },
    "en_US": {
        "app.title": "NetOps Studio",
        "nav.dashboard": "Dashboard",
        "nav.discovery": "Discovery",
        "nav.diagnostics": "Diagnostics",
        "nav.speedtest": "Speed Test",
        "nav.subnet": "Subnet Calc",
        "nav.codec": "Codec",
        "action.run": "Run",
        "action.stop": "Stop",
        "action.clear": "Clear",
        "status.ready": "Ready",
        "common.online": "Online",
        "common.offline": "Offline",
    },
}


class I18n:
    def __init__(self, locale: str = "zh_CN") -> None:
        self.locale = locale
        self._dict = dict(_DEFAULTS.get(locale, _DEFAULTS["zh_CN"]))

    def load_file(self, path: str) -> None:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                self._dict.update(json.load(f))

    def set_locale(self, locale: str) -> None:
        self.locale = locale
        self._dict = dict(_DEFAULTS.get(locale, _DEFAULTS["zh_CN"]))

    def tr(self, key: str, default: str = "") -> str:
        return self._dict.get(key, default or key)


# 全局实例
_i18n = I18n()


def tr(key: str, default: str = "") -> str:
    return _i18n.tr(key, default)


def set_locale(locale: str) -> None:
    _i18n.set_locale(locale)


def i18n() -> I18n:
    return _i18n
