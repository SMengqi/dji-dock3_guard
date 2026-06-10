# DJI Dock Guard

DJI 大疆机场 3 飞行安全评估与告警系统。

**纯告警系统**：观测 broker 数据 → 评估风险 → 分级告警；**不下发任何指令**。

## 设计文档

[2026-06-05-dji-dock-guard-design.md](./2026-06-05-dji-dock-guard-design.md)（v2 当前版本，2700+ 行）

## 子系统

| 子系统 | 入口 | 说明 |
|---|---|---|
| **A. 实时告警** | `python -m dock_guard` | MQTT 订阅 → 规则评估 → 钉钉/Webhook/面板 |
| **B. 离线分析** | `python -m dock_guard.analytics` | 读 `sim_dji_cloud_service` 录制目录 → 电池/航时/链路统计（设计 §13） |

## 实现进度（v2 实施）

- [x] Phase 0 — 项目骨架（pyproject / Dockerfile / 配置模板 / conftest）
- [x] Phase 1 — Config 加载 + types
- [x] Phase 2 — Envelope + ReplaySource
- [x] Phase 3 — Aggregator + PhaseMachine + FactsRing
- [x] Phase 4 — RuleEngine + custom_fn 白名单（custom_fn 实装留 Phase 11）
- [x] Phase 5 — AlertCoordinator + alerts.jsonl
- [x] Phase 6 — DingTalk / Webhook 通道
- [x] Phase 7 — MqttSource
- [x] **M1 — LIVE → 钉钉端到端打通**（订真 broker、规则 fire、钉钉收卡片、alerts.jsonl 落 DISPATCHED）
- [ ] Phase 8 — FastAPI 控制面 + Panel SSE
- [ ] Phase 9 — Prometheus / JsonlSink rotation / 多 dock
- [ ] Phase 10 — 跨切（鉴权 / §10.5 治理）
- [ ] Phase 11 — §5.4 custom_fn 三函数实装 + 其余 §11 🟡
- [ ] Phase 12 — §12 验收 + CI 强制门
- [ ] Phase 13+ — §13 离线分析子系统

## M1 快速启动（sim 联调，30 秒跑通）

前提：钉钉自定义机器人已建好（加签模式），手头有 webhook URL + sign 密钥。

```bash
# 1) 装包 + 复制配置模板
./install.sh --copy-config
source .venv/bin/activate

# 2) 编辑 .env，填两段关键值
#    - DINGTALK_BOT_WEBHOOK_PRIMARY  (line 15)  ← 粘贴 webhook URL
#    - DINGTALK_BOT_SECRET_PRIMARY   (line 16)  ← 粘贴加签密钥 (SEC 开头)
#    sim 模式下 MQTT_USERNAME / MQTT_PASSWORD 可填占位符 (例如 "x" / "x"),
#    mosquitto 不开 auth.
vi .env

# 3) 改 config/runtime.yaml: broker_url 用 sim 的本地 mosquitto, TLS 关
#    mqtt:
#      broker_url:  tcp://localhost:1883
#      tls:
#        enabled:   false
#    subscriptions:
#      - dock_sn: 8UUXN7N00A0GAA   (示例录制样本)
#        enabled: true
vi config/runtime.yaml

# 4) (另一终端) 起本地 mosquitto + sim 播一段录制
#    详见 ../sim_dji_cloud_service/2026-05-21-sim-dji-cloud-operations-manual.md §5
mosquitto -p 1883 &
cd ../sim_dji_cloud_service
sim-dji play sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145 \
    --mqtt-url tcp://localhost:1883 --speed 1.0

# 5) 启动 dock_guard
python -m dock_guard
# 看 stdout 摘要包含 'dingtalk = ["ops-primary"]'.
# 录制中触发 emergency_stop / wind_exceeded / heavy_rain 等规则时,
# 钉钉群应收到带 [BLOCK]/[RETURN] 前缀的 Markdown 卡片,
# data/alerts.jsonl 同步落 DISPATCHED 行.
```

切换真 broker：改 `.env` 的 `MQTT_BROKER_URL / USERNAME / PASSWORD`，重启 `python -m dock_guard`（环境变量不热更，§15.10）。

离线回放（不需要 broker，最快验证规则与告警链路是否走通）：

```bash
python -m dock_guard --replay $(pwd)/../sim_dji_cloud_service/sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145/
```

Docker：

```bash
docker compose up -d dock_guard
```

更多脚本选项：`./install.sh --help`；配置详见设计文档 §15「配置文件总览」。

## 兄弟服务

本仓库依赖同 monorepo 下：

- `cloud_api/sim_dji_cloud_service/` — MQTT 录制服务，输出 `recordings/<sn>_<ts>/` 供本服务回放与离线分析

设计契约见 §0.4：本服务**不重复采集原始 envelope**。
