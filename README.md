# NetOps Studio / 网维工作台

面向**网络工程师 / IT 运维**的集成化桌面运维工作台。桌面端优先（Windows / Linux / macOS），
覆盖发现、诊断、测速、子网、编解码等日常运维场景，并预留配置管理、监控告警、IPAM、排障、
安全管理、抓包、流量分析、带外机房、音视频物联、报表、AI 助手、集成 API、平台权限等能力。

> 开发文档见 `docs/开发文档.md`（规划版 v0.2）。

## 架构（四层）

```
表现层 GUI  →  应用服务层 (TabRegistry/EventBus/AsyncWorker/DI/Theme/i18n)
           →  核心引擎层 core（纯 Python，禁止 import PySide6）
           →  基础设施与数据层 (Config/DeviceStore/History/Crypto)
```

- `core/` 引擎层与 UI 完全解耦（纯 Python，可单测、可未来 Web 复用）。
- 插件式 Tab 注册（`TabRegistry`），新功能即"注册一个新 tab + 复用 core"。
- 协作式异步（`AsyncWorker`），禁用线程强杀。
- 事件总线（`EventBus`）解耦模块与仪表盘。

## 当前进度（阶段 1 · MVP）

| 状态 | 模块 | 说明 |
|------|------|------|
| ✅ | 仪表盘 | KPI + 近期设备，订阅事件总线 |
| ✅ | 资产与发现 | 多线程 ping 扫描 + 主机名/MAC/OUI |
| ✅ | 连通性诊断 | Ping / Traceroute / 端口扫描 / DNS / HTTP |
| ✅ | 性能与测速 | iperf3 封装 + 外网 HTTP 探针测速 |
| ✅ | 子网计算器 | CIDR 计算 / 子网拆分 |
| ✅ | 编解码工具 | Base64/URL/哈希/进制/时间戳/JWT/PEM |
| ✅ | 工具箱 | 掩码/通配符、OUI、强密码、带宽、单位换算、WOL、进制、时间戳 |
| ✅ | 配置管理 | 多厂商接入、备份/回滚/下发、模板、变更审计、合规基线、凭据保险箱(AES) |
| ✅ | 监控与告警 | SNMP 轮询、MIB 浏览器、阈值告警、Syslog 接收、趋势 |
| ✅ | 安全管理 | 开放端口审计、弱口令、证书到期、CVE 查询、防火墙审计 |
| ✅ | 专项排障 | 多厂商 IP 冲突、DHCP 冲突、STP/环路检测 |
| ✅ | 抓包分析 | tshark 抓包、协议分布、会话 TopN、异常流量 |
| ✅ | 音视频物联 | ONVIF 发现、RTSP/SDP 流探测、VoIP MOS 评估 |
| ✅ | 报表自动化 | 巡检编排、HTML/PDF/Word/Excel 一键导出、通知集成 |
| ✅ | IP 地址管理 | 网段分配、冲突检测、利用率统计、与发现对账 |
| ✅ | 流量深度分析 | NetFlow/sFlow/IPFIX 解析、Top Talker、应用占比、异常 |
| ✅ | 带外与机房 | Redfish/ipmitool 遥测、PDU、温湿度、机架管理 |
| ✅ | AI 智能助手 | 意图解析、厂商命令生成、知识库、规则诊断 |
| ✅ | 集成与 API | 本地 FastAPI、CSV/JSON 导入导出、Zabbix/Prometheus/NetBox 桩 |
| ✅ | 平台与权限 | RBAC、审计日志、插件注册、命令面板、自定义仪表盘 |

> 全部 18 个规划模块（含仪表盘与子网计算器）均已实现。设备相关功能（SNMP/SSH/抓包/带外）在无对应二进制或依赖时优雅降级并报错。

## 快速开始

```bash
# 依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt   # 测试

# 运行（任选其一，必须在仓库根目录 E:\Code\netops_studio 下执行）

# 方式 A：一键启动器（最省事，推荐）
python run.py

# 方式 B：以包模块方式运行（需先进入 src/ 目录）
cd src
python -m netops_studio.main

# 测试
pytest
```

> ⚠️ 不要直接 `python src/netops_studio/main.py` 或在该文件所在目录 `python main.py`——
> main.py 使用相对导入（`from .app import ...`），直接当脚本跑会因「找不到父包」而报
> `ImportError: attempted relative import with no known parent package`。请用上面的方式 A 或 B。

> 注意：运行 GUI 需要桌面环境（PySide6 + Qt）。无显示环境可用 pytest 验证 core 纯逻辑。

## 打包

```bash
pyinstaller -D src/netops_studio/main.py --name NetOpsStudio
# iperf3 二进制放入 src/netops_studio/resources/bin/<os>/
```
