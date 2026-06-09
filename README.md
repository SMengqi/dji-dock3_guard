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
- [ ] Phase 1 — Config 加载 + types
- [ ] Phase 2 — Envelope + ReplaySource
- [ ] Phase 3 — Aggregator + PhaseMachine + FactsRing
- [ ] Phase 4 — RuleEngine + custom_fn 白名单
- [ ] Phase 5 — AlertCoordinator + alerts.jsonl
- [ ] Phase 6 — DingTalk / Webhook / SSE 通道
- [ ] Phase 7 — MqttSource
- [ ] Phase 8 — FastAPI 控制面
- [ ] Phase 9 — Prometheus / JsonlSink
- [ ] Phase 10 — CI 强制门
- [ ] Phase 11 — §13 离线分析子系统

## 快速开始

```bash
# 一键装包 (自动建 venv + pip install -e ".[dev]" + 复制配置模板)
./install.sh --copy-config

source .venv/bin/activate
vi .env                            # 填 MQTT 凭证 / 钉钉 webhook / ADMIN_TOKEN
vi config/runtime.yaml             # 填 dock_sn
vi config/dingtalk_robots.yaml

# 离线回放 (最快验证)
python -m dock_guard --replay $(pwd)/../sim_dji_cloud_service/sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145/

# 实时运行
python -m dock_guard

# Docker
docker compose up -d dock_guard
```

更多脚本选项：`./install.sh --help`

详见设计文档 §15「配置文件总览」。

## 兄弟服务

本仓库依赖同 monorepo 下：

- `cloud_api/sim_dji_cloud_service/` — MQTT 录制服务，输出 `recordings/<sn>_<ts>/` 供本服务回放与离线分析

设计契约见 §0.4：本服务**不重复采集原始 envelope**。
