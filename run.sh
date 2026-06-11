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
# 管理:
#   status               查看各模式运行状态
#   stop <模式>          优雅停止某模式 (SIGTERM -> graceful close, 30s 内未退则 SIGKILL)
#   logs <模式>          tail -f 某模式最新日志
#   help                 显示本帮助
#
# 例:
#   ./run.sh replay                                                    # 用脚本顶部默认目录 + 倍速 0
#   ./run.sh replay ../sim_dji_cloud/recordings/8UU.../  1.0           # 临时指定目录 + 原速
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

# python -m dock_guard 的额外参数 (config-dir / data-dir 一般走自动检测, 不必填)
EXTRA_ARGS=""

# HTTP 控制面 (与 _run_live 的 --http-host / --http-port 默认对齐)
HTTP_HOST="127.0.0.1"
HTTP_PORT="8081"

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
  sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
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
