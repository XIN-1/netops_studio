"""平台与权限模块（gui/platform_module.py）。对应 core/rbac.py。

功能：用户/角色表格 + 权限检查、命令面板（过滤 ACTIONS）、审计日志查看、
插件列表、自定义仪表盘 KPI 配置、主题/语言切换（调用 app.theme / app.i18n）。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
)

from ..app import container
from ..app.i18n import i18n, set_locale, tr
from ..app.theme import Theme
from ..core import rbac
from ..core.rbac import AuditLog, DashboardConfig, User


# 内置示例用户（演示 RBAC 与权限检查）
_SAMPLE_USERS = [
    User("alice", "admin"),
    User("bob", "operator"),
    User("carol", "viewer"),
]


class PlatformModule(QWidget):
    """平台与权限模块（对应 core/rbac.py）。

    聚合用户/角色权限检查、命令面板（基于 ACTIONS 过滤）、审计日志查看、插件列
    表、自定义仪表盘 KPI 配置，以及主题/语言切换（调用 app.theme / app.i18n）。
    所有操作均经 AuditLog 留痕。注意：本模块直接使用 Qt 控件，未走 widgets 复
    用组件。
    """

    def __init__(self) -> None:
        super().__init__()
        # 主题对象：优先复用容器中的全局 Theme，否则自建一个本地实例
        self.theme: Theme = container.get("theme") if container.has("theme") else Theme("light")
        self.audit = AuditLog()
        rbac.ensure_sample_plugins()

        self._build_ui()
        self._refresh_users()
        self._refresh_plugins()
        self._refresh_audit()
        self._load_dashboard()

    # ======================================================================
    # UI 构建
    # ======================================================================
    def _build_ui(self) -> None:
        """构建顶层布局：主题/语言切换条 + 五个功能 Tab。"""
        root = QVBoxLayout(self)

        # ---- 顶部条：主题 / 语言切换 ----
        bar = QHBoxLayout()
        self.theme_btn = QPushButton("切换主题")
        self.theme_btn.clicked.connect(self._toggle_theme)
        self.lang_btn = QPushButton("切换语言")
        self.lang_btn.clicked.connect(self._toggle_lang)
        self.status = QLabel("就绪")
        self.status.setProperty("role", "muted")
        bar.addWidget(self.theme_btn)
        bar.addWidget(self.lang_btn)
        bar.addWidget(self.status)
        bar.addStretch()
        root.addLayout(bar)

        # ---- Tab 容器 ----
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_rbac_tab(), "用户与权限")
        self.tabs.addTab(self._build_command_tab(), "命令面板")
        self.tabs.addTab(self._build_audit_tab(), "审计日志")
        self.tabs.addTab(self._build_plugin_tab(), "插件")
        self.tabs.addTab(self._build_dashboard_tab(), "仪表盘配置")
        root.addWidget(self.tabs, 1)

    # ---- 用户与权限 ----
    def _build_rbac_tab(self) -> QWidget:
        """构建「用户与权限」Tab：用户表 + 权限检查表单。"""
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("用户与角色"))
        self.user_table = QTableWidget(0, 2)
        self.user_table.setHorizontalHeaderLabels(["用户名", "角色"])
        self.user_table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.user_table)

        form = QFormLayout()
        self.user_combo = QComboBox()
        for u in _SAMPLE_USERS:
            self.user_combo.addItem(f"{u.name} ({u.role})", u)
        self.action_combo = QComboBox()
        for action in sorted(rbac.ACTIONS.keys()):
            self.action_combo.addItem(f"{action} — {rbac.ACTIONS[action]}", action)
        self.action_combo.setEditable(True)
        form.addRow("用户", self.user_combo)
        form.addRow("动作 (action)", self.action_combo)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        self.check_btn = QPushButton("检查权限")
        self.check_btn.clicked.connect(self._check_permission)
        btn_row.addWidget(self.check_btn)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self.perm_result = QLabel("—")
        self.perm_result.setProperty("role", "title")
        lay.addWidget(self.perm_result)
        return w

    # ---- 命令面板 ----
    def _build_command_tab(self) -> QWidget:
        """构建「命令面板」Tab：关键字过滤 ACTIONS 并支持双击触发。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("命令面板（输入关键字过滤动作）"))
        self.cmd_filter = QLineEdit()
        self.cmd_filter.setPlaceholderText("过滤：如 ping / 配置 / sync ...")
        self.cmd_filter.textChanged.connect(self._filter_actions)
        lay.addWidget(self.cmd_filter)

        self.cmd_list = QListWidget()
        self.cmd_list.itemDoubleClicked.connect(self._run_action)
        lay.addWidget(self.cmd_list)
        self._filter_actions("")

        self.cmd_status = QLabel("双击动作可执行（演示：写入审计日志）")
        self.cmd_status.setProperty("role", "muted")
        lay.addWidget(self.cmd_status)
        return w

    # ---- 审计日志 ----
    def _build_audit_tab(self) -> QWidget:
        """构建「审计日志」Tab：搜索框 + 日志列表。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        head = QHBoxLayout()
        self.audit_search = QLineEdit()
        self.audit_search.setPlaceholderText("查询：用户 / 动作 / 详情关键字")
        self.audit_search.textChanged.connect(self._refresh_audit)
        self.audit_refresh = QPushButton("刷新")
        self.audit_refresh.clicked.connect(self._refresh_audit)
        head.addWidget(QLabel("审计日志"))
        head.addWidget(self.audit_search)
        head.addWidget(self.audit_refresh)
        lay.addLayout(head)

        self.audit_list = QListWidget()
        lay.addWidget(self.audit_list)
        return w

    # ---- 插件 ----
    def _build_plugin_tab(self) -> QWidget:
        """构建「插件」Tab：插件列表 + 重新扫描按钮。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        head = QHBoxLayout()
        self.plugin_scan_btn = QPushButton("重新扫描")
        self.plugin_scan_btn.clicked.connect(self._refresh_plugins)
        head.addWidget(QLabel("插件列表"))
        head.addStretch()
        head.addWidget(self.plugin_scan_btn)
        lay.addLayout(head)

        self.plugin_list = QListWidget()
        lay.addWidget(self.plugin_list)
        return w

    # ---- 仪表盘配置 ----
    def _build_dashboard_tab(self) -> QWidget:
        """构建「仪表盘配置」Tab：KPI 勾选项 + 保存/重载按钮。"""
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("自定义仪表盘（选择要显示的 KPI）"))
        self.kpi_checks: dict = {}
        box = QVBoxLayout()
        for key in rbac.DEFAULT_DASHBOARD:
            cb = QCheckBox(key)
            self.kpi_checks[key] = cb
            box.addWidget(cb)
        lay.addLayout(box)

        btn_row = QHBoxLayout()
        self.kpi_save = QPushButton("保存")
        self.kpi_save.clicked.connect(self._save_dashboard)
        self.kpi_load = QPushButton("重新加载")
        self.kpi_load.clicked.connect(self._load_dashboard)
        btn_row.addWidget(self.kpi_save)
        btn_row.addWidget(self.kpi_load)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        return w

    # ======================================================================
    # 行为
    # ======================================================================
    def _refresh_users(self) -> None:
        """渲染内置示例用户表（用户名/角色）。"""
        self.user_table.setRowCount(len(_SAMPLE_USERS))
        for i, u in enumerate(_SAMPLE_USERS):
            self.user_table.setItem(i, 0, QTableWidgetItem(u.name))
            self.user_table.setItem(i, 1, QTableWidgetItem(u.role))

    def _check_permission(self) -> None:
        """检查所选用户对所选动作的权限并着色展示，同时写入审计。"""
        user: User = self.user_combo.currentData()
        action = self.action_combo.currentData() or self.action_combo.currentText().strip()
        ok = rbac.check_permission(user.role, action)
        self.perm_result.setText(f"{action}: {'允许' if ok else '拒绝'}")
        self.perm_result.setStyleSheet(
            "color: #1aab5b" if ok else "color: #e54545"
        )
        self.audit.record(user, action, f"权限检查 -> {'允许' if ok else '拒绝'}")

    def _filter_actions(self, query: str) -> None:
        """按关键字过滤命令面板动作列表（用 UserRole 携带动作名）。"""
        self.cmd_list.clear()
        for name in rbac.search_actions(query):
            item = QListWidgetItem(f"{name} — {rbac.ACTIONS[name]}")
            item.setData(Qt.UserRole, name)
            self.cmd_list.addItem(item)

    def _run_action(self, item: QListWidgetItem) -> None:
        """双击命令面板项：触发动作（演示）并记入审计。"""
        action = item.data(Qt.UserRole)
        self.cmd_status.setText(f"已触发：{action}（已记入审计）")
        self.audit.record("operator", action, "命令面板执行（演示）")

    def _refresh_audit(self) -> None:
        """按搜索关键字刷新审计日志列表（最新在上）。"""
        q = self.audit_search.text() if hasattr(self, "audit_search") else ""
        logs = self.audit.search(q)
        self.audit_list.clear()
        for e in logs[::-1]:  # 最新在上
            line = f"[{e.get('ts')}] {e.get('user')}({e.get('role')}) {e.get('action')}: {e.get('detail')}"
            self.audit_list.addItem(QListWidgetItem(line))

    def _refresh_plugins(self) -> None:
        """扫描并渲染插件列表；无插件时给出占位提示。"""
        plugins = rbac.scan_plugins()
        self.plugin_list.clear()
        if not plugins:
            self.plugin_list.addItem(QListWidgetItem("（未发现插件）"))
            return
        for p in plugins:
            line = f"{p.get('name', p.get('id'))}  v{p.get('version', '?')}  — {p.get('description', '')}"
            self.plugin_list.addItem(QListWidgetItem(line))

    def _load_dashboard(self) -> None:
        """从持久化配置加载仪表盘 KPI 勾选状态。"""
        cfg = DashboardConfig().load()
        for key, cb in self.kpi_checks.items():
            cb.setChecked(bool(cfg.get(key, True)))

    def _save_dashboard(self) -> None:
        """保存当前仪表盘 KPI 勾选状态并留痕。"""
        states = {k: cb.isChecked() for k, cb in self.kpi_checks.items()}
        DashboardConfig().save(states)
        self.status.setText("仪表盘配置已保存")
        self.audit.record("operator", "dashboard.configure", str(states))

    # ---- 主题 / 语言 ----
    def _toggle_theme(self) -> None:
        """在 light/dark 间切换主题，并应用全局 QSS。"""
        new_mode = "dark" if self.theme.token.name == "light" else "light"
        self.theme.set_mode(new_mode)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(self.theme.qss())
        self.status.setText(f"主题：{new_mode}")
        self.audit.record("operator", "theme.toggle", new_mode)

    def _toggle_lang(self) -> None:
        """在 zh_CN / en_US 间切换语言并刷新本模块可见文案。"""
        cur = i18n().locale
        new_locale = "en_US" if cur == "zh_CN" else "zh_CN"
        set_locale(new_locale)
        self.status.setText(f"语言：{new_locale}")
        self._retranslate()
        self.audit.record("operator", "lang.toggle", new_locale)

    def _retranslate(self) -> None:
        # 更新可在运行时翻译的标签（其余为数据驱动内容）
        self.tabs.setTabText(0, "用户与权限")
        self.tabs.setTabText(1, "命令面板")
        self.tabs.setTabText(2, "审计日志")
        self.tabs.setTabText(3, "插件")
        self.tabs.setTabText(4, "仪表盘配置")
        self.theme_btn.setText("切换主题")
        self.lang_btn.setText("切换语言")
        self.status.setText(tr("status.ready", "就绪"))
