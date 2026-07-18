"""配置管理模块（gui/config_module.py）。对应 core/config_mgmt.py。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from ..app import AsyncWorker
from ..app.async_worker import JobBase
from ..core import config_mgmt


class ConfigJob(JobBase):
    """后台执行配置管理操作（网络/文件 IO），结果以 dict 回传。"""

    def __init__(self, op: str, **kwargs: object) -> None:
        super().__init__()
        self.op = op
        self.kwargs = kwargs

    def run_job(self) -> None:
        if self.op == "backup":
            res = config_mgmt.connect_and_backup(
                self.kwargs["device"], self.kwargs["creds"]
            )
        elif self.op == "push":
            res = config_mgmt.push_config(
                self.kwargs["device"], self.kwargs["creds"], self.kwargs["content"]
            )
        elif self.op == "rollback":
            res = config_mgmt.rollback(self.kwargs["device"], self.kwargs["ts"])
        else:
            raise ValueError(f"未知操作：{self.op}")
        self.signals.result.emit({"op": self.op, "data": res})


class ConfigModule(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.worker = AsyncWorker()
        self.vault = config_mgmt.CredentialVault()
        root = QVBoxLayout(self)

        # ---- 表单：设备信息 ----
        form = QFormLayout()
        self.device = QLineEdit("core-sw1")
        self.host = QLineEdit("192.168.1.1")
        self.vendor = QComboBox()
        self.vendor.addItems(["cisco", "huawei", "h3c", "juniper"])
        self.user = QLineEdit("admin")
        self.password = QLineEdit("")
        self.password.setEchoMode(QLineEdit.Password)
        self.cred_name = QLineEdit("default")
        self.ts = QLineEdit("")
        self.ts.setPlaceholderText("回滚时间戳，留空=最新")
        form.addRow("设备名", self.device)
        form.addRow("地址", self.host)
        form.addRow("厂商", self.vendor)
        form.addRow("用户名", self.user)
        form.addRow("密码", self.password)
        form.addRow("凭据名(保险箱)", self.cred_name)
        form.addRow("回滚时间戳", self.ts)
        root.addLayout(form)

        # ---- 操作按钮 ----
        btn_row = QHBoxLayout()
        self.backup_btn = QPushButton("备份")
        self.rollback_btn = QPushButton("回滚")
        self.check_btn = QPushButton("合规检查")
        self.push_btn = QPushButton("下发")
        self.save_cred_btn = QPushButton("保存凭据")
        self.diff_btn = QPushButton("差异比对")
        for b in (self.backup_btn, self.rollback_btn, self.check_btn,
                  self.push_btn, self.save_cred_btn, self.diff_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.status = QLabel("就绪")
        root.addWidget(self.status)

        # ---- 配置内容编辑区（合规/下发/比对）----
        self.content = QTextEdit()
        self.content.setPlaceholderText("粘贴设备配置文本：用于合规检查 / 下发 / 差异比对")
        root.addWidget(QLabel("配置内容"))
        root.addWidget(self.content)

        # ---- 结果展示 ----
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        root.addWidget(QLabel("结果 / 差异 / 合规违规"))
        root.addWidget(self.result)

        # ---- 信号绑定 ----
        self.backup_btn.clicked.connect(self._backup)
        self.rollback_btn.clicked.connect(self._rollback)
        self.check_btn.clicked.connect(self._check)
        self.push_btn.clicked.connect(self._push)
        self.save_cred_btn.clicked.connect(self._save_cred)
        self.diff_btn.clicked.connect(self._diff)

    # -- 工具 --
    def _creds(self) -> dict:
        return {
            "host": self.host.text().strip(),
            "username": self.user.text().strip(),
            "password": self.password.text(),
            "vendor": self.vendor.currentText(),
        }

    def _submit(self, op: str, **kwargs: object) -> None:
        self.status.setText(f"执行 {op} …")
        self.result.clear()
        job = ConfigJob(op, **kwargs)
        self.worker.submit(job, on_result=self._show, on_error=self._err)

    def _err(self, msg: str) -> None:
        self.status.setText("错误")
        self.result.setPlainText(msg)

    # -- 操作：网络类（走 AsyncWorker）--
    def _backup(self) -> None:
        self._submit("backup", device=self.device.text().strip(), creds=self._creds())

    def _push(self) -> None:
        self._submit("push", device=self.device.text().strip(),
                     creds=self._creds(), content=self.content.toPlainText())

    def _rollback(self) -> None:
        ts = self.ts.text().strip()
        if not ts:
            backups = config_mgmt.list_backups(self.device.text().strip())
            if not backups:
                self._err("无可用备份")
                return
            ts = backups[-1]
        self._submit("rollback", device=self.device.text().strip(), ts=ts)

    # -- 操作：本地纯函数（直接执行）--
    def _check(self) -> None:
        text = self.content.toPlainText()
        rules = config_mgmt.default_baseline_rules()
        violations = config_mgmt.check_baseline(text, rules)
        if not violations:
            self.status.setText("合规：未发现违规")
            self.result.setPlainText("✓ 通过全部基线检查")
            return
        self.status.setText(f"合规：{len(violations)} 处违规")
        lines = [f"发现 {len(violations)} 处违规：", ""]
        for v in violations:
            loc = f" 行{v['line']}" if v.get("line") else ""
            lines.append(f"- [{v['name']}]{loc}: {v['detail']}")
        self.result.setPlainText("\n".join(lines))

    def _diff(self) -> None:
        device = self.device.text().strip()
        backups = config_mgmt.list_backups(device)
        if not backups:
            self._err("无可用备份，无法比对")
            return
        ts = self.ts.text().strip() or backups[-1]
        try:
            old = config_mgmt.get_backup(device, ts)
        except FileNotFoundError as exc:
            self._err(str(exc))
            return
        new = self.content.toPlainText()
        diff = config_mgmt.diff_configs(old, new)
        self.status.setText(f"差异：基准 {ts}")
        self.result.setPlainText(diff or "（无差异）")

    def _save_cred(self) -> None:
        name = self.cred_name.text().strip()
        if not name:
            self._err("凭据名不能为空")
            return
        self.vault.add_credential(name, self.user.text().strip(), self.password.text())
        self.status.setText(f"已保存凭据：{name}")
        self.result.setPlainText(f"凭据 '{name}' 已加密入库。\n"
                                 f"当前凭据：{', '.join(self.vault.list_names())}")

    # -- 结果渲染 --
    def _show(self, res: dict) -> None:
        op = res.get("op")
        data = res.get("data")
        if op == "backup":
            self.status.setText("备份完成")
            self.result.setPlainText(
                f"设备：{data['device']}\n厂商：{data['vendor']}\n"
                f"时间戳：{data['timestamp']}\n路径：{data['backup_path']}\n\n"
                f"--- running-config ---\n{data['running_config']}"
            )
        elif op == "push":
            self.status.setText("下发完成")
            self.result.setPlainText(
                f"设备：{data['device']}\n下发命令数：{len(data['commands'])}\n\n"
                f"--- 设备回显 ---\n{data['output']}"
            )
        elif op == "rollback":
            self.status.setText("回滚（已取回备份内容）")
            self.result.setPlainText(data)
