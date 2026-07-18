"""国际化（app/i18n.py）。

zh_CN / en_US 资源加载，tr(key) 取词。纯 Python，不依赖 Qt。对应开发文档 §7。

查找与回退机制：
- 内置 _DEFAULTS 词表提供基础词条；若指定 locale 在表中缺失，则回退到 zh_CN，
  保证任何 locale 都能取到至少一个中文兜底。
- tr(key, default)：先查当前词表；查不到时返回 default，若 default 也为空则返回
  key 本身（即「找不到就用 key 当文案」，便于发现未翻译项）。
- 支持通过 load_file() 从 resources/locales 的 JSON 文件扩展词条（合并进 _dict）。
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
    """多语言词典持有者。实例通过 set_locale 切换语言，tr 取词。"""

    def __init__(self, locale: str = "zh_CN") -> None:
        self.locale = locale
        # 复制一份避免污染 _DEFAULTS 常量；locale 缺失时回退 zh_CN。
        self._dict = dict(_DEFAULTS.get(locale, _DEFAULTS["zh_CN"]))

    def load_file(self, path: str) -> None:
        # 从 JSON 文件合并扩展词条；文件不存在则静默跳过（基础词表仍可用）。
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                self._dict.update(json.load(f))

    def set_locale(self, locale: str) -> None:
        # 切换语言：重建 _dict（以新 locale 为基础，缺失则回退 zh_CN）。
        # 注意：会丢弃此前 load_file 合并的扩展词条，仅保留内置词表。
        self.locale = locale
        self._dict = dict(_DEFAULTS.get(locale, _DEFAULTS["zh_CN"]))

    def tr(self, key: str, default: str = "") -> str:
        # 查表 -> 回退 default -> 再回退 key 本身。
        return self._dict.get(key, default or key)


# 全局实例
_i18n = I18n()


def tr(key: str, default: str = "") -> str:
    """模块级便捷取词，委托给全局 _i18n 实例。"""
    return _i18n.tr(key, default)


def set_locale(locale: str) -> None:
    """切换全局语言（影响后续所有 tr() 取词）。"""
    _i18n.set_locale(locale)


def i18n() -> I18n:
    """获取全局 I18n 实例（便于直接读取 locale 或批量取词）。"""
    return _i18n
