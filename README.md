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

## 实现进度（按产品能力 Stage 划分）

每个 Stage = 一个可对外演示的产品能力（不是按代码模块）。详见设计文档 §11.0。

- [x] **Stage 1 — 实时告警最小闭环**：订真 broker / sim broker → 阶段机识别 → 规则触发 → 钉钉收到 `[BLOCK]/[RETURN]` 卡片 → `alerts.jsonl` 落 DISPATCHED；含 `run.sh` 后台运维 + SIGTERM graceful + sim 联调 + 真 broker 切换。涵盖 16 个 commit `a2678cc → 4477df0`。
- [ ] **Stage 2 — 待产品选定**：A 运维控制台 / B 多机场上线 / C 告警精度 / D 工程化验收 / E 离线复盘骨架 / F 离线分析-电池 / G 离线分析-RTH / H 离线分析-链路。8 个能力候选见 §11.0.2。

## M1 快速启动（sim 联调，30 秒跑通）

前提：钉钉自定义机器人已建好（加签模式），手头有 webhook URL + sign 密钥。

```bash
# 1) 装包 (默认顺手 cp *.yaml.example *.yaml 与 .env.example .env, 不覆盖已有)
./install.sh
source .venv/bin/activate

# 2) 编辑 .env 的两段钉钉值 (line 15 webhook URL, line 16 SEC... 密钥)
vi .env

# 3) 改 config/runtime.yaml 的 subscriptions[0].dock_sn 为 8UUXN7N00A0GAA
#    (sim 模式可顺手把 broker_url 改为 tcp://localhost:1883 + tls.enabled: false)
vi config/runtime.yaml

# 4) 离线回放验证 (后台启动, 不依赖 broker, 最快)
./run.sh replay                      # 默认目录 + 倍速 0
./run.sh logs replay                 # 看进度

# 5) 切实时模式 (sim broker 或真 broker, 由 .env 决定)
./run.sh live
./run.sh status                      # 看后台状态
./run.sh stop live                   # 优雅停止 (SIGTERM -> graceful)
```

`./run.sh help` 看全部命令。前台调试不走 `run.sh`，直接 `python -m dock_guard ...` 看 stdout。

sim 模式 broker 启动（另一终端）：

```bash
mosquitto -p 1883 &
cd ../sim_dji_cloud_service
sim-dji play sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145 \
    --mqtt-url tcp://localhost:1883 --speed 1.0
```

切换真 broker：改 `.env` 的 `MQTT_BROKER_URL / USERNAME / PASSWORD`，`./run.sh stop live && ./run.sh live` 重启（环境变量不热更，§15.10）。

Docker：

```bash
docker compose up -d dock_guard
```

更多脚本选项：`./install.sh --help` / `./run.sh help`；配置详见设计文档 §15「配置文件总览」。

## 兄弟服务

本仓库依赖同 monorepo 下：

- `cloud_api/sim_dji_cloud_service/` — MQTT 录制服务，输出 `recordings/<sn>_<ts>/` 供本服务回放与离线分析

设计契约见 §0.4：本服务**不重复采集原始 envelope**。
