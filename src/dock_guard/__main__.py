"""dock_guard CLI 入口.

Phase 0: argparse 骨架.
Phase 1: 加载 config + 打印汇总.
Phase 2: --replay 模式跑 ReplaySource, 统计每 topic envelope 数 + duration.
后续 Phase 逐步填入: aggregator / rules / coordinator / notify / http.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from dock_guard import __version__
from dock_guard.aggregator import DockAggregator
from dock_guard.config import AppConfig, MissingEnvVarError, load_app_config
from dock_guard.coordinator import AlertCoordinator, Decision, JsonlAlertSink
from dock_guard.ingest import MqttSource, ReplaySource
from dock_guard.notify import DingTalkChannel, NotificationBus, Router
from dock_guard.rules import RuleEngine
from dock_guard.types import ChannelKind, Severity, TopicKey


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI parser. v2.1 后 CLI 仅含运行模式开关, 监控对象走 runtime.yaml."""
    p = argparse.ArgumentParser(
        prog="dock_guard",
        description="DJI Dock 3 飞行安全评估与告警系统 (v2, 纯告警, 不下发指令)",
        epilog="详见 2026-06-05-dji-dock-guard-design.md §15.8",
    )
    p.add_argument("--version", action="version", version=f"dock_guard {__version__}")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--replay",
        metavar="DIR",
        type=Path,
        help="离线回放模式, 读 recordings/<sn>_<ts>/ 目录而非订阅 broker",
    )
    mode.add_argument(
        "--emit-baseline",
        metavar="PATH",
        type=Path,
        help="只读分析模式, 跑完写 tests/replay/baselines/*.json 即退出, 不开 broker",
    )
    p.add_argument(
        "--replay-speed",
        type=float,
        default=1.0,
        help="回放速度: 1.0=原速 (默认), 0=尽可能快",
    )

    p.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="配置目录, 默认: /app/config 存在则用 (docker), 否则用 ./config (本机)",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="数据 (jsonl/snapshot) 目录, 默认: /app/data 存在则用 (docker), 否则用 ./data",
    )

    p.add_argument("--enable-hot-reload", action="store_true",
                   help="允许 SIGHUP / POST /admin/reload-rules 热更规则")
    p.add_argument("--global-mute-on-boot", action="store_true",
                   help="启动即全局通知静默 (可由 POST /admin/global_mute 解除)")
    p.add_argument("--require-auth-all", action="store_true",
                   help="所有 HTTP 端点强制鉴权 (默认仅 /admin/*)")

    p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARN", "ERROR"],
                   default="INFO",
                   help="stdout 日志级别, 不影响 jsonl 文件")

    return p


def _resolve_dir(user_arg: Path | None, container: Path, local: Path) -> Path:
    """优先级: --user 显式参数 > /app/<x> (docker 容器内) > ./<x> (本机 cwd).

    `user_arg=None` 表示用户没传 --config-dir/--data-dir, 走自动检测.
    """
    if user_arg is not None:
        return user_arg.resolve()
    if container.exists():
        return container
    return local.resolve()


def main(argv: list[str] | None = None) -> int:
    # 自动加载本地 .env 以注入 MQTT_* / DINGTALK_* 等环境变量.
    # override=False: 已 export 的系统环境变量优先, .env 仅补缺失.
    # 找不到 .env 不报错 (docker / 已 export 场景照旧).
    from dotenv import load_dotenv  # 延迟 import: 仅 CLI 启动时需要
    load_dotenv(override=False)

    parser = build_parser()
    args = parser.parse_args(argv)

    config_dir = _resolve_dir(args.config_dir, Path("/app/config"), Path("./config"))
    data_dir = _resolve_dir(args.data_dir, Path("/app/data"), Path("./data"))

    print(f"dock_guard {__version__}  [Phase 1: config loaded]")
    print()
    print(f"  config_dir         = {config_dir}")
    print(f"  data_dir           = {data_dir}")
    print(f"  log_level          = {args.log_level}")
    if args.replay:
        print(f"  mode               = REPLAY ({args.replay})")
        print(f"  replay_speed       = {args.replay_speed}")
    elif args.emit_baseline:
        print(f"  mode               = EMIT-BASELINE ({args.emit_baseline})")
    else:
        print("  mode               = LIVE (MQTT broker subscribe)")
    print(f"  hot_reload         = {args.enable_hot_reload}")
    print(f"  global_mute_boot   = {args.global_mute_on_boot}")
    print(f"  require_auth_all   = {args.require_auth_all}")
    print()

    # Phase 1: 加载并汇总配置.
    try:
        cfg = load_app_config(config_dir)
    except FileNotFoundError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except MissingEnvVarError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    print("config summary:")
    print(f"  runtime.schema_version       = {cfg.runtime.schema_version}")
    print(f"  mqtt.broker_url              = {cfg.runtime.mqtt.broker_url}")
    print(f"  mqtt.username                = {cfg.runtime.mqtt.username}")
    print(f"  mqtt.password                = {'*' * 8}  (length={len(cfg.runtime.mqtt.password)})")
    print(f"  subscriptions (enabled)      = "
          f"{[s.dock_sn for s in cfg.runtime.subscriptions if s.enabled]}")
    print(f"  wildcard_subscribe.enabled   = {cfg.runtime.wildcard_subscribe.enabled}")
    enabled_topics = sorted(
        k.value for k, v in cfg.runtime.topic_defaults.as_map().items() if v
    )
    print(f"  topic_defaults (enabled)     = {enabled_topics}")
    print(f"  mode_code_map.drone_model    = {cfg.mode_code_map.drone_model}")
    print(f"  mode_code_map.values_count   = {len(cfg.mode_code_map.values)}")
    print(f"  alert_levels.coordinator     = "
          f"cooldown={cfg.alert_levels.coordinator.default_cooldown_ms}ms, "
          f"em_floor={cfg.alert_levels.coordinator.emergency_floor_cooldown_ms}ms")
    print()

    # ── Phase 2-6: --replay 跑 ReplaySource + Aggregator ──────────
    if args.replay:
        return asyncio.run(_run_replay(
            args.replay, speed=args.replay_speed, cfg=cfg, data_dir=data_dir
        ))

    # ── Phase 7: LIVE = 订 MQTT broker ─────────────────────────────
    return asyncio.run(_run_live(cfg, data_dir=data_dir))


def _build_notification_bus(cfg: AppConfig) -> NotificationBus | None:
    """M1: 按 cfg.dingtalk_robots 装配 NotificationBus.

    返回 None 表示未配置任何通道, AlertCoordinator 会降级为仅写 alerts.jsonl.
    """
    if cfg.dingtalk_robots is None or not cfg.dingtalk_robots.robots:
        return None
    channels = {
        ChannelKind.DINGTALK: DingTalkChannel(list(cfg.dingtalk_robots.robots)),
    }
    router = Router(cfg.alert_levels, cfg.notification_routing)
    return NotificationBus(channels, router)


async def _run_live(cfg: AppConfig, *, data_dir: Path = Path("data")) -> int:
    """M1 LIVE 模式: 订真实 MQTT broker -> Aggregator -> Rules ->
    AlertCoordinator -> NotificationBus -> DingTalkChannel.
    永远跑直到 Ctrl-C / SIGTERM.
    """
    src = MqttSource(cfg)
    enabled = [s.dock_sn for s in cfg.runtime.subscriptions if s.enabled]
    print(f"live source: MQTT {cfg.runtime.mqtt.broker_url}")
    print(f"  docks       = {enabled}")
    print(f"  qos         = {cfg.runtime.mqtt.qos}")
    print(f"  tls         = {cfg.runtime.mqtt.tls.enabled}")
    if cfg.dingtalk_robots is not None:
        robot_ids = [r.id for r in cfg.dingtalk_robots.robots]
        print(f"  dingtalk    = {robot_ids}")
    else:
        print("  dingtalk    = (未配置 dingtalk_robots.yaml, 告警只入 alerts.jsonl)")
    print()
    print("注: 本服务仅 SUBSCRIBE; 任何 PUBLISH 到 thing/+/services 都是缺陷 (设计 §0.2).")
    print("Ctrl-C 停止.")
    print()

    # M1 仍仅支持单 dock + 单 drone; 多 dock 留待 Phase 9.
    if len(enabled) != 1:
        print(f"warning: M1 仅支持 1 个启用的 dock, 检测到 {len(enabled)}", file=sys.stderr)
        return 2
    dock_sn = enabled[0]

    agg = DockAggregator(dock_sn, cfg)
    engine = RuleEngine(cfg.rules, agg) if cfg.rules is not None else None
    bus = _build_notification_bus(cfg)
    coordinator: AlertCoordinator | None = None
    if engine is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        alerts_path = data_dir / "alerts.jsonl"
        coordinator = AlertCoordinator(
            cfg, sink=JsonlAlertSink(alerts_path), bus=bus
        )

    total = 0
    last_print_ts = 0
    try:
        async for env in src:
            total += 1
            agg.apply(env)
            if engine is not None and coordinator is not None:
                batch = engine.evaluate()
                if batch:
                    # M1: 走 async 路径以触发 NotificationBus.dispatch (-> DingTalk).
                    await coordinator.handle_batch_async(batch)
            # 每 1000 条心跳一次
            if total - last_print_ts >= 1000:
                print(f"  ... {total} envelopes processed, "
                      f"phase={agg.current_phase.value}")
                last_print_ts = total
    except KeyboardInterrupt:
        print("\nshutdown requested (Ctrl-C)")
    finally:
        if coordinator is not None:
            coordinator.close()
        if bus is not None:
            await bus.close()
        await src.close()
    return 0


async def _run_replay(
    recording_dir: Path, *, speed: float, cfg: AppConfig,
    data_dir: Path = Path("data"),
) -> int:
    """Phase 3 验证模式: 跑 ReplaySource 喂 Aggregator, 打印 envelope 分布 + phase 时间线."""
    try:
        src = ReplaySource(recording_dir, speed=speed)
    except FileNotFoundError as e:
        print(f"replay error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"replay error: {e}", file=sys.stderr)
        return 2

    print("replay source:")
    print(f"  dir          = {src.recording_dir}")
    print(f"  dock_sn      = {src.dock_sn}")
    print(f"  drone_sn     = {src.drone_sn}")
    print(f"  duration_ms  = {src.manifest.ended_at_recv_ms - src.manifest.started_at_recv_ms}")
    print(f"  jsonl_files  = {len(src.manifest.jsonl_files)}")
    print(f"  speed        = {speed}  (0 = as fast as possible)")
    print()
    print("iterating envelopes...")

    agg = DockAggregator(src.dock_sn, cfg)
    engine = RuleEngine(cfg.rules, agg) if cfg.rules is not None else None

    coordinator: AlertCoordinator | None = None
    if engine is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        alerts_path = data_dir / "alerts.jsonl"
        coordinator = AlertCoordinator(cfg, sink=JsonlAlertSink(alerts_path))

    counts: Counter[TopicKey] = Counter()
    total = 0
    first_ts: int | None = None
    last_ts: int | None = None
    transitions = []
    verdicts = []
    alert_records = []

    async for env in src:
        counts[env.topic_key] += 1
        total += 1
        if first_ts is None:
            first_ts = env.recv_ts_ms
        last_ts = env.recv_ts_ms
        agg.apply(env)
        transitions.extend(agg.drain_phase_transitions())
        if engine is not None:
            batch = engine.evaluate()
            verdicts.extend(batch)
            if coordinator is not None and batch:
                alert_records.extend(coordinator.handle_batch(batch))

    if coordinator is not None:
        coordinator.close()
    await src.close()

    print(f"  total envelopes = {total}")
    if first_ts is not None and last_ts is not None:
        print(f"  span_ms         = {last_ts - first_ts}")
    print("  by topic_key (sorted):")
    for key in sorted(counts, key=lambda k: k.value):
        print(f"    {key.value:25s} {counts[key]:6d}")

    # phase 时间线
    print()
    print(f"phase transitions ({len(transitions)}):")
    if transitions:
        offset = transitions[0].ts_ms
        for tr in transitions:
            print(
                f"  +{tr.ts_ms - offset:7d}ms  "
                f"{tr.phase_from.value:10s} -> {tr.phase_to.value:10s}  "
                f"src={tr.phase_source_to.value:20s}  "
                f"mc={tr.mode_code}  h={tr.drone_height}  "
                f"reason={tr.reason}"
            )

    # verdict 时间线 (Phase 4)
    print()
    print(f"verdicts ({len(verdicts)}):")
    if verdicts:
        by_code: Counter[str] = Counter()
        for v in verdicts:
            by_code[f"{v.code}({v.level.name})"] += 1
        print("  by code:")
        for code, n in by_code.most_common():
            print(f"    {code:50s} {n:6d}")
        # 显示前 5 条 + 后 2 条
        offset = verdicts[0].ts_ms
        print("  first 5:")
        for v in verdicts[:5]:
            print(f"    +{v.ts_ms - offset:7d}ms  [{v.level.name:9s}] {v.code:35s} {v.suggested_action}")
        if len(verdicts) > 5:
            print(f"  ... ({len(verdicts) - 7} between) ...")
            for v in verdicts[-2:]:
                print(f"    +{v.ts_ms - offset:7d}ms  [{v.level.name:9s}] {v.code:35s} {v.suggested_action}")

    # 最高 severity 摘要
    if verdicts:
        max_sev: Severity = max(v.level for v in verdicts)
        print(f"  max severity: {max_sev.name}")

    # Phase 5: 三闸抑制汇总
    if alert_records:
        print()
        dispatched = sum(1 for r in alert_records if r.decision == Decision.DISPATCHED)
        suppressed = len(alert_records) - dispatched
        print(f"alert coordinator ({len(alert_records)} records):")
        print(f"  dispatched   = {dispatched}")
        print(f"  suppressed   = {suppressed}")
        # 各 gate 抑制原因 breakdown
        gate_reasons: Counter[str] = Counter()
        for r in alert_records:
            if r.decision == Decision.SUPPRESSED:
                for g, status in r.gates.items():
                    if status != "pass":
                        gate_reasons[f"{g}:{status}"] += 1
        if gate_reasons:
            print("  suppress reasons:")
            for reason, n in gate_reasons.most_common():
                print(f"    {reason:35s} {n:6d}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
