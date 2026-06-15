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

- [x] **Stage 1 — 实时告警最小闭环** ✅（2026-06-10 真实环境验证）：订真 broker / sim broker → 阶段机识别 → 规则触发 → 钉钉收到 `[BLOCK]/[RETURN]` 卡片 → `alerts.jsonl` 落 DISPATCHED；含 `run.sh` 后台运维 + SIGTERM graceful + sim 联调 + 真 broker 切换。涵盖 24 个 commit `a2678cc → fc1c638`。
- [x] **Stage 2 — 运维控制台** ✅（2026-06-10 真实环境验证）：FastAPI + Panel SSE + ADMIN_TOKEN 鉴权；`/healthz` `/readyz` `/events`（SSE 推 alert + phase_transition）`/admin/mute/{dock_sn}` `/admin/global_mute` `/admin/mutes` `/admin/reload-rules`；`./run.sh admin <subcmd>` 一行 curl 包装。涉及 §7.2 + §8 + §9.3 + §10.1 + §10.5。
- [x] **Stage 3-D — 工程化验收 + CI 强制门** ✅（2026-06-12 GitHub Actions 首跑通过）：5 commit (`14c3cc8 33b3d6a 9fba652 c8bed70 e6a99f0`)。涵盖：(1) `tests/ci/test_static_checks.py` 静态门（禁 publish / 禁原始 envelope 落盘 / `custom_fn` 白名单 + 禁 dotted-eval）(2) `custom_fn` 异常隔离 + 自产 `RULE_EVAL_FAILED` WARN (3) `tests/replay/` baseline 回归（首份 `8UUXN7N00A0GAA_20260605-165145.json` 2739 envelopes / 14 transitions / 4660 verdicts / 24 DISPATCHED）+ `scripts/regen_replay_baseline.py` (4) `.github/workflows/ci.yml` 跑 ruff + 257 测 (5) `PULL_REQUEST_TEMPLATE.md` 强制 "变化原因 + 是否 regen baseline"。涉及 §12.4 全部 + §5.4。
- [x] **Stage 4-E — 离线复盘骨架** ✅（2026-06-14 真实环境验证）：4 commit (`51beec7 83fed75 f096faf` + T5 docs)。`python -m dock_guard.analytics <dir>` 一行从 sim 录制出 markdown + json 报告，批量自动汇总 `index.md`。涵盖：(1) `analytics/{models,collector,report,__main__}.py` 子包；FlightReport schema v2 + 5 个指标（阵风峰值/最低电量/最长 OFFLINE/飞行时长/告警统计）(2) CLI 自动 single/batch 识别 + `--out`/`--force`/`--quiet`/`--config-dir` (3) ASCII Gantt 60 列封顶 + 中文译名跟 dingtalk 同口径 (4) `tests/replay/_helpers.py` 改成 collector 薄壳 (D15)；baseline v1 测试零回归 (5) 28 测（10 collector + 8 report + 8 CLI + 3 e2e 含 PREFLIGHT_DOCK_TILT / INFLIGHT_BATTERY_LOW 真录制断言）。涉及设计 §13.1–§13.3 + §13.8。
- [ ] Stage 3+ 余下候选池：B 多机场 / C 告警精度 / F-H 三个离线分析器。详见设计文档 §11.0.3。

## M1 快速启动（sim 联调，30 秒跑通）

前提：钉钉自定义机器人已建好（加签模式），手头有 webhook URL + sign 密钥。

```bash
# 1) 装包 (默认顺手 cp *.yaml.example *.yaml 与 .env.example .env, 不覆盖已有)
./install.sh
source .venv/bin/activate

# 2) 改 .env 一处, runtime.yaml 一般不动:
#    MQTT_BROKER_URL=tcp://localhost:1883   # sim; 真 broker 改 ssl://
#    MQTT_USERNAME=x                         # sim 无 auth 填占位即可
#    MQTT_PASSWORD=x
#    MQTT_DOCK_SN=8UUXN7N00A0GAA             # 机场 SN, sim 录制样本是这个
#    ADMIN_TOKEN=<python -c "import secrets; print(secrets.token_hex(32))" 的输出>
#    DINGTALK_BOT_WEBHOOK_PRIMARY=https://oapi.dingtalk.com/robot/send?access_token=<你的token>
#    DINGTALK_BOT_SECRET_PRIMARY=SEC<你的加签密钥>
vi .env

# 3) 离线回放验证 (后台启动, 不依赖 broker, 最快)
./run.sh replay                      # 默认目录 + 倍速 0
./run.sh logs replay                 # 看进度

# 4) 切实时模式 (sim broker 或真 broker, 由 .env 决定)
./run.sh live
./run.sh status                      # 看后台状态
./run.sh stop live                   # 优雅停止 (SIGTERM -> graceful)

# 5) HTTP 控制面 (Stage 2) — 直接走 ./run.sh admin 子命令
./run.sh admin health                                          # /healthz + /readyz
./run.sh admin events                                          # SSE 流: alert + phase_transition (Ctrl-C 退)
./run.sh admin mutes                                           # 查当前静默
./run.sh admin mute 8UUXN7N00A0GAA 3600                        # 静默该 dock 1 小时
./run.sh admin unmute 8UUXN7N00A0GAA                           # 解除
./run.sh admin global_mute "off-hours"                         # 全局静默
./run.sh admin global_unmute
./run.sh admin reload                                          # 重读 config/rules.yaml 热替规则

# 原始 curl 也可以 (TOKEN 从 .env 抽 hex):
TOKEN=$(grep -oP '^ADMIN_TOKEN=\K[A-Fa-f0-9]+' .env | head -1)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8081/docs    # FastAPI Swagger
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

## 离线复盘（Stage 4-E）

跑 sim 录制目录出复盘报告：

```bash
# 单录制 -> <recording>/dock_guard_report/{report.json,report.md}
./run.sh analytics ../sim_dji_cloud_service/sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145/

# 父目录 -> N 份报告 + index.md 汇总
./run.sh analytics

# 指定输出目录 + 强制重跑已分析的
./run.sh analytics ../sim_dji_cloud/recordings/ --out /tmp/reports/ --force

# 也可直接走 python 入口
python -m dock_guard.analytics <dir> [--out DIR] [--force] [--quiet] [--config-dir DIR]
```

报告内容：摘要 / 关键指标（阵风峰值、最低电量、最长 OFFLINE、飞行时长、告警统计）/ 阶段 ASCII Gantt（60 列封顶） / 告警时间线 / 告警频次表。完整设计见 §13。

## 兄弟服务

本仓库依赖同 monorepo 下：

- `cloud_api/sim_dji_cloud_service/` — MQTT 录制服务，输出 `recordings/<sn>_<ts>/` 供本服务回放与离线分析

设计契约见 §0.4：本服务**不重复采集原始 envelope**。

## 项目暂停状态（2026-06-14）

dock_guard 完成 Stage 1 → 2 → 3-D → 4-E 后进入**长期暂停**状态（预期数月后重启）。本节是接手者的入口。

### 当前已完成的产品能力

- **Stage 1** 实时告警最小闭环：MQTT → 阶段机 → 11 条规则 → 钉钉卡片 + `alerts.jsonl`
- **Stage 2** 运维控制台：FastAPI + SSE + ADMIN_TOKEN + `/admin/{mute,global_mute,mutes,reload-rules,events,health}`
- **Stage 3-D** 工程化验收：静态门 + custom_fn 异常隔离 + replay baseline 回归 + GitHub Actions CI
- **Stage 4-E** 离线复盘骨架：录制目录 → markdown + JSON 报告（5 个指标 + ASCII Gantt + 告警时间线）+ 批量 `index.md`

### 暂停期间运行

broadxt 上 `./run.sh live` 进程**继续运行**收集真实告警 + `alerts.jsonl`；钉钉告警继续投。遇到误报临时静音 `./run.sh admin mute <dock_sn> <duration_s>`。无需特殊维护。

### 未来重启 entry points

| 候选 | 缺什么 | spec 章节 | 工作量 |
|---|---|---|---|
| **B** | 多机场支持 + Prometheus 指标 + 日志轮转 + docker compose 一键起 | §9.1 §9.2 §14 §15.9 | 中 (1-2 周) |
| **C** | `custom_fn` 三函数实装（电池基线 / RTH 时间 / 续航估算） | §5.4 + §13.4–§13.5 | 大（需 ≥10 架次样本, Stage 4-E 已可产）|
| **F** | 离线分析器: 电池基线（拟合 `battery_reference.yaml`） | §13.4 | 大 |
| **G** | 离线分析器: RTH 时间模型 | §13.5 | 中 |
| **H** | 离线分析器: 链路抖动 | §13.6 | 中 |
| - | 多 broker schema（现单 broker；2 个 broker 临时拆 2 进程亦可） | spec 未明文 | 中 |
| - | 会话化（单录制跨多架次切分） | §13.7 + §13.11 TBD #1 | 小-中 |
| - | tcpdump CI 强制门（验证仅 SUBSCRIBE） | §12.4 | 小（需 root） |

### 重启入口（按顺序）

1. **看 `2026-06-05-dji-dock-guard-design.md` §11.0 路线图**（本机草稿）
2. **跑 `pytest tests/` 确保 ✅ 起跑线**（基线还能 reproduce）
3. **选 B/C/F/G/H 任一**，参 `../sim_dji_cloud_service/` 开发模型：
   - 先写 `<日期>-dji-dock-guard-<feature>-design.md`（不入 git）
   - 再写 `<日期>-dji-dock-guard-<feature>-prp.md`（不入 git）
   - 按 PRP 的 Task 1..N + TDD 5 步实施
