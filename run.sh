#!/usr/bin/env bash
# dock_guard 启动脚本: 后台跑 LIVE / REPLAY, 日志落 ./logs/.
# 风格参考 ../sim_dji_cloud_service/sim_dji_cloud/run.sh
#
# 用法:
#   ./run.sh <模式|命令>
#
# 模式 (nohup 后台启动, 终端关闭也不停):
#   live                 LIVE 模式: 订阅 MQTT broker, 跑直到 stop / SIGTERM
#   replay [目录] [倍速] REPLAY 模式: 读 recordings/<sn>_<ts>/ 离线回放
#                        默认目录见脚本顶部 DEFAULT_REPLAY_DIR, 默认倍速 0 (尽快)
#
# 离线复盘 (Stage 4-E, 前台跑, 不 nohup):
#   analytics [目录] [...] 录制目录 -> markdown + json 报告 (父目录则批量 + index.md)
#                        默认目录见脚本顶部 DEFAULT_ANALYTICS_DIR
#                        额外参数透传给 python -m dock_guard.analytics:
#                          --out <dir>   --force   --quiet   --config-dir <dir>
#
# 电池基线分析 (Stage 5-F, 前台跑, 不 nohup):
#   battery-analyzer [父目录] [...]
#                        跨架次电池统计 -> battery_reference.yaml + report.md
#                        要求子目录已跑过 Stage 4-E (出 v3 report.json)
#                        默认目录见脚本顶部 DEFAULT_BATTERY_DIR
#                        额外参数: --out <dir>  --min-samples N  --quiet
#
# 管理:
#   status               查看各模式运行状态
#   stop <模式>          优雅停止某模式 (SIGTERM -> graceful close, 30s 内未退则 SIGKILL)
#   logs <模式>          tail -f 某模式最新日志
#   help                 显示本帮助
#
# 例:
#   ./run.sh replay                                                    # 用脚本顶部默认目录 + 倍速 0
#   ./run.sh replay ../sim_dji_cloud/recordings/8UU.../  1.0           # 临时指定目录 + 原速
#   ./run.sh analytics                                                 # 默认目录, 批量出报告 + index.md
#   ./run.sh analytics ../sim_dji_cloud/recordings/8UU.../             # 单架次报告
#   ./run.sh analytics recordings/ --out /tmp/reports/ --force         # 输出到独立目录 + 强重跑
#   ./run.sh live                                                      # 启动实时
#   ./run.sh status                                                    # 看哪些在跑
#   ./run.sh logs live                                                 # 跟踪 live 日志
#   ./run.sh stop live                                                 # 优雅停 live
#
# 前台调试不走 run.sh, 直接 `python -m dock_guard ...` 看 stdout.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

# 自动激活 venv (与 install.sh 创建的 .venv 对齐)
[ -f .venv/bin/activate ] && source .venv/bin/activate

# ================= 可编辑配置 (按机器/场景改这里) =================

# REPLAY 默认目录: 同 monorepo 下兄弟 sim 服务的录制样本
DEFAULT_REPLAY_DIR="../sim_dji_cloud_service/sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145"

# REPLAY 默认倍速: 0=尽可能快 (常用于 CI / 冒烟), 1.0=原速 (用于真实时序排查)
DEFAULT_REPLAY_SPEED="0"

# Stage 4-E 离线分析默认录制目录 (传父目录 = 批量; 传单录制 = 单份)
DEFAULT_ANALYTICS_DIR="../sim_dji_cloud_service/sim_dji_cloud/recordings"

# Stage 5-F 电池分析默认父目录 (要求子目录都已 Stage 4-E 出 v3 report.json)
DEFAULT_BATTERY_DIR="../sim_dji_cloud_service/sim_dji_cloud/recordings"

# python -m dock_guard 的额外参数 (config-dir / data-dir 一般走自动检测, 不必填)
EXTRA_ARGS=""

# HTTP 控制面: 默认从 .env 读 HTTP_HOST / HTTP_PORT, 缺失则用硬编码兜底.
# 保证 python 端 --http-port 解析与 run.sh admin 客户端拼 URL 用同一个值.
# 注: set -e + pipefail 下 grep 无匹配会返非零, 这里全部 || true 兜底,
# 否则用户 .env 没加这两行就会让 run.sh 整个静默退出.
_env_get() {
  local val=""
  if [ -f .env ]; then
    val=$(grep -oP "^$1=\K[^[:space:]#]+" .env 2>/dev/null | head -1 || true)
  fi
  printf '%s' "$val"
}
HTTP_HOST="$(_env_get HTTP_HOST || true)"; HTTP_HOST="${HTTP_HOST:-127.0.0.1}"
HTTP_PORT="$(_env_get HTTP_PORT || true)"; HTTP_PORT="${HTTP_PORT:-8081}"

# ==================================================================

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

# 后台启动: nohup 脱离 SIGHUP + 重定向日志 + 脱离终端 stdin; 记录 pid + latest 软链.
launch() {
  local name="$1"; shift
  local pidf="$LOG_DIR/${name}.pid"
  if [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; then
    echo "[run] $name 已在运行 (pid=$(cat "$pidf"))； 要重启先: ./run.sh stop $name"
    exit 1
  fi
  local ts log
  ts="$(date +%Y%m%d-%H%M%S)"
  log="$LOG_DIR/${name}-${ts}.log"
  nohup "$@" >"$log" 2>&1 < /dev/null &
  local pid=$!
  disown 2>/dev/null || true
  echo "$pid" > "$pidf"
  ln -sf "$(basename "$log")" "$LOG_DIR/${name}-latest.log"
  echo "[run] $name 已后台启动  pid=$pid"
  echo "[run] 日志: $log"
  echo "[run] 看日志: ./run.sh logs $name   停止: ./run.sh stop $name"
}

stop_mode() {
  local name="$1"
  local pidf="$LOG_DIR/${name}.pid"
  [ -f "$pidf" ] || { echo "[run] $name 未在运行 (无 pid 文件)"; return 0; }
  local pid
  pid="$(cat "$pidf")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"   # SIGTERM -> __main__ 转 KeyboardInterrupt -> graceful close
    echo "[run] 已向 $name (pid=$pid) 发送 SIGTERM (优雅收尾, 最多等 30s)"
    local i
    for i in $(seq 1 60); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "[run] $name (pid=$pid) 30s 内未退出, 发送 SIGKILL"
      kill -9 "$pid" 2>/dev/null || true
      sleep 0.5
    fi
  else
    echo "[run] $name 进程不存在 (pid=$pid), 清理 pid 文件"
  fi
  rm -f "$pidf"
}

status() {
  printf "%-10s %-8s %s\n" "模式" "PID" "状态"
  shopt -s nullglob
  local any=0
  for pidf in "$LOG_DIR"/*.pid; do
    any=1
    local name pid
    name="$(basename "$pidf" .pid)"
    pid="$(cat "$pidf")"
    if kill -0 "$pid" 2>/dev/null; then
      printf "%-10s %-8s %s\n" "$name" "$pid" "运行中"
    else
      printf "%-10s %-8s %s\n" "$name" "$pid" "已停止 (残留 pid 文件)"
    fi
  done
  [ $any -eq 0 ] && echo "(无任何后台进程在跑)"
}

usage() {
  sed -n '2,44p' "$0" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

admin 子命令 (Stage 2 控制面, 走 .env 的 ADMIN_TOKEN):
  admin mutes                            列出当前静默状态
  admin mute <dock_sn> [duration_s]      设 per-dock 静默 (默认永久)
  admin unmute <dock_sn>                 解除 per-dock 静默
  admin global_mute [reason]             开全局静默
  admin global_unmute                    解除全局静默
  admin reload                           重读 config/rules.yaml -> 热替规则
  admin events                           SSE 流式订阅 (Ctrl-C 退出)
  admin health                           GET /healthz + /readyz
EOF
}

# ── admin: 从 .env 抽 token + 通用 curl wrapper ───────────────────
_admin_token() {
  if [ ! -f .env ]; then
    echo "[run] .env 不存在; 先 ./install.sh 或 cp .env.example .env" >&2
    return 2
  fi
  local t
  t=$(grep -oP '^ADMIN_TOKEN=\K[A-Fa-f0-9]+' .env | head -1)
  if [ -z "$t" ]; then
    echo "[run] .env 里没找到 ADMIN_TOKEN= 行 (必须是 hex)" >&2
    return 2
  fi
  echo "$t"
}

_admin_url() {
  echo "http://${HTTP_HOST}:${HTTP_PORT}$1"
}

_admin_curl() {
  local token method path data
  token="$(_admin_token)" || exit 2
  method="$1"; path="$2"; data="${3:-}"
  if [ -n "$data" ]; then
    curl -sS -X "$method" \
      -H "Authorization: Bearer $token" \
      -H "Content-Type: application/json" \
      -d "$data" \
      "$(_admin_url "$path")"
  else
    curl -sS -X "$method" \
      -H "Authorization: Bearer $token" \
      "$(_admin_url "$path")"
  fi
  echo   # curl 不 trailing newline
}

admin_subcommand() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    mutes)
      _admin_curl GET /admin/mutes | python -m json.tool
      ;;
    mute)
      local dock="${1:?用法: ./run.sh admin mute <dock_sn> [duration_s]}"
      local dur="${2:-0}"
      _admin_curl POST "/admin/mute/$dock" \
        "{\"enabled\":true,\"duration_s\":${dur}}" | python -m json.tool
      ;;
    unmute)
      local dock="${1:?用法: ./run.sh admin unmute <dock_sn>}"
      _admin_curl POST "/admin/mute/$dock" \
        '{"enabled":false}' | python -m json.tool
      ;;
    global_mute)
      local reason="${1:-manual}"
      _admin_curl POST /admin/global_mute \
        "{\"enabled\":true,\"reason\":\"${reason}\"}" | python -m json.tool
      ;;
    global_unmute)
      _admin_curl POST /admin/global_mute \
        '{"enabled":false}' | python -m json.tool
      ;;
    reload)
      _admin_curl POST /admin/reload-rules | python -m json.tool
      ;;
    events)
      local token
      token="$(_admin_token)" || exit 2
      # -N: 不缓冲, SSE 流就要立刻看到帧.
      exec curl -N -H "Authorization: Bearer $token" "$(_admin_url /events)"
      ;;
    health)
      echo "--- /healthz ---"
      curl -sS "$(_admin_url /healthz)"; echo
      echo "--- /readyz ---"
      curl -sS -w "\n[HTTP %{http_code}]\n" "$(_admin_url /readyz)"
      ;;
    ""|help|-h|--help)
      sed -n '/^admin 子命令/,/^EOF$/p' <(usage)
      ;;
    *)
      echo "未知 admin 子命令: $sub" >&2
      exit 1
      ;;
  esac
}

mode="${1:-}"
shift || true

case "$mode" in
  live)
    # 注: 启动后立刻返回; 看启动 stdout 是否抱怨 dingtalk / broker 见 logs/live-latest.log
    # shellcheck disable=SC2086
    launch live python -m dock_guard $EXTRA_ARGS
    ;;
  replay)
    dir="${1:-$DEFAULT_REPLAY_DIR}"
    speed="${2:-$DEFAULT_REPLAY_SPEED}"
    if [ ! -d "$dir" ]; then
      echo "[run] replay 目录不存在: $dir" >&2
      echo "       提示: 改脚本顶部 DEFAULT_REPLAY_DIR 或 ./run.sh replay <绝对/相对目录>" >&2
      exit 2
    fi
    # shellcheck disable=SC2086
    launch replay python -m dock_guard --replay "$dir" --replay-speed "$speed" $EXTRA_ARGS
    ;;
  analytics)
    # Stage 4-E 离线复盘: 录制目录 -> markdown + json 报告 (+ 批量 index.md).
    # 前台跑, 不 nohup; 单架次几秒, 批量 N 份按 N×几秒计.
    dir="${1:-$DEFAULT_ANALYTICS_DIR}"
    shift || true
    if [ ! -d "$dir" ]; then
      echo "[run] analytics 目录不存在: $dir" >&2
      echo "       提示: 改脚本顶部 DEFAULT_ANALYTICS_DIR 或 ./run.sh analytics <目录>" >&2
      exit 2
    fi
    # 透传剩余参数 (--out / --force / --quiet 等)
    exec python -m dock_guard.analytics "$dir" "$@"
    ;;
  battery-analyzer)
    # Stage 5-F 电池基线分析: 父目录 v3 report.json -> battery_reference.yaml + report.md.
    # 前台跑, 不 nohup; 100 架次几十秒.
    dir="${1:-$DEFAULT_BATTERY_DIR}"
    shift || true
    if [ ! -d "$dir" ]; then
      echo "[run] battery-analyzer 目录不存在: $dir" >&2
      echo "       提示: 改脚本顶部 DEFAULT_BATTERY_DIR 或 ./run.sh battery-analyzer <目录>" >&2
      exit 2
    fi
    # 透传剩余参数 (--out / --min-samples / --quiet 等)
    exec python -m dock_guard.analytics.analyzers.battery "$dir" "$@"
    ;;
  status)
    status
    ;;
  stop)
    stop_mode "${1:?用法: ./run.sh stop <模式>}"
    ;;
  logs)
    tail -f "$LOG_DIR/${1:?用法: ./run.sh logs <模式>}-latest.log"
    ;;
  admin)
    admin_subcommand "$@"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "未知模式: $mode" >&2
    echo
    usage
    exit 1
    ;;
esac
