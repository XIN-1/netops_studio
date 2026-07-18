"""AI 智能助手模块（gui/ai_module.py）。对应 core/ai_assist.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..core.ai_assist import (
    ACTIONS, VENDORS, assist,
)

_ACTION_CN = {
    "ping": "Ping 探测",
    "traceroute": "路由跟踪",
    "scan": "网络扫描",
    "speedtest": "性能测速",
    "subnet": "子网计算",
    "whois": "WHOIS 查询",
    "portscan": "端口扫描",
    "help": "帮助",
}


class AiModule(QWidget):
    """AI 智能助手模块（对应 core/ai_assist.py）。

    以对话形式接收自然语言问题，调用 ``assist()`` 同步完成意图解析、命令生成、
    知识库检索与诊断建议，并将结构化结果渲染到消息区。支持多厂商命令风格切换。
    """

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)

        # 顶部：厂商选择
        top = QHBoxLayout()
        top.addWidget(QLabel("厂商:"))
        self.vendor = QComboBox()
        self.vendor.addItems(VENDORS)
        self.vendor.setCurrentText("cisco")
        top.addWidget(self.vendor)
        top.addStretch()
        root.addLayout(top)

        # 消息区
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.setPlaceholderText(
            "输入问题，AI 助手将解析意图、生成命令、检索知识库并给出诊断建议…"
        )
        root.addWidget(self.history, stretch=1)

        # 输入区
        bottom = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "例如：帮我 ping 一下 8.8.8.8 / 华为设备怎么配 trunk / 网络丢包怎么排查"
        )
        self.input.returnPressed.connect(self._on_send)
        self.send_btn = QPushButton("发送")
        self.send_btn.clicked.connect(self._on_send)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self.history.clear)
        bottom.addWidget(self.input, stretch=1)
        bottom.addWidget(self.send_btn)
        bottom.addWidget(self.clear_btn)
        root.addLayout(bottom)

        self._print_banner()

    # ------------------------------------------------------------------
    def _print_banner(self) -> None:
        """打印助手开场白，列出所有支持的动作（来自 ACTIONS）。"""
        self._append(
            "AI",
            "你好，我是 NetOps 智能助手 🤖。可处理："
            + "、".join(_ACTION_CN.get(a, a) for a in ACTIONS)
            + "。\n输入自然语言即可，例如：『traceroute 到 1.1.1.1』"
              "『端口扫描 192.168.1.1 的 80』『网络丢包怎么排查』。",
        )

    def _on_send(self) -> None:
        """发送消息：调用 assist() 解析并渲染意图/命令/知识库/诊断四段式回复。"""
        q = self.input.text().strip()
        if not q:
            return
        self._append("你", q)
        try:
            res = assist(q, self.vendor.currentText())
        except Exception as exc:  # noqa: BLE001
            self._append("AI", f"处理出错：{exc}")
            self.input.clear()
            return

        intent = res["intent"]
        action = intent.get("action", "help")
        target = intent.get("target", "")

        lines = [
            f"【意图解析】动作: {_ACTION_CN.get(action, action)}"
            + (f"  目标: {target}" if target else "")
            + (f"  参数: {intent.get('params')}" if intent.get("params") else "")
        ]

        if action == "help":
            lines.append(
                "【帮助】请描述你的需求，例如：ping / traceroute / 子网计算 / "
                "端口扫描 / WHOIS / 网络扫描 / 测速，或描述故障现象让我诊断。"
            )
        else:
            cmd = res.get("command", "")
            if cmd:
                lines.append(f"【生成命令 · {self.vendor.currentText()}】\n  {cmd}")

        kb = res.get("kb_answer", "")
        if kb:
            lines.append(f"【知识库】\n  {kb}")

        diag = res.get("diagnosis") or []
        if diag:
            lines.append("【诊断建议】")
            lines.extend(f"  {i}. {s}" for i, s in enumerate(diag, 1))

        self._append("AI", "\n".join(lines))
        self.input.clear()

    # ------------------------------------------------------------------
    def _append(self, role: str, text: str) -> None:
        """向消息区追加一条带角色前缀的消息，并滚动到底部。"""
        prefix = "👤 " if role == "你" else "🤖 "
        self.history.append(f"{prefix}{role}：{text}")
        # 滚动到底部
        sb = self.history.verticalScrollBar()
        sb.setValue(sb.maximum())
