#!/usr/bin/env bash
# install.sh — dock_guard 一键装包脚本
#
# 用法:
#   ./install.sh                # 装包+开发依赖
#   ./install.sh --no-dev       # 仅生产依赖
#   ./install.sh --recreate     # 删除现有 .venv 重建
#   ./install.sh --copy-config  # 同时复制 *.yaml.example -> *.yaml (仅当目标不存在)
#
# 多次运行安全; 已存在的资源不会被覆盖.

set -euo pipefail

# ─── 配置 ─────────────────────────────────────────────────────────
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=12
VENV_DIR=".venv"
EXTRAS="[dev]"
COPY_CONFIG=0
RECREATE=0

# ─── 解析参数 ─────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --no-dev)       EXTRAS="" ;;
    --copy-config)  COPY_CONFIG=1 ;;
    --recreate)     RECREATE=1 ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "未知参数: $arg" >&2
      echo "运行 ./install.sh --help 查看用法" >&2
      exit 2
      ;;
  esac
done

# ─── 颜色/打印工具 ─────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_OK=$'\033[32m'; C_INFO=$'\033[36m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_END=$'\033[0m'
else
  C_OK=""; C_INFO=""; C_WARN=""; C_ERR=""; C_END=""
fi
log()   { echo "${C_INFO}==>${C_END} $*"; }
ok()    { echo "${C_OK}✓${C_END} $*"; }
warn()  { echo "${C_WARN}!${C_END} $*"; }
fail()  { echo "${C_ERR}✗${C_END} $*" >&2; exit 1; }

# ─── 工作目录 ─────────────────────────────────────────────────────
cd "$(dirname "$(readlink -f "$0")")"
log "工作目录: $(pwd)"

# ─── 检查 Python ──────────────────────────────────────────────────
log "检查 Python >= ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}"
PYTHON_BIN=""
for candidate in python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver=$("$candidate" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")
    ver_major=${ver%%.*}
    ver_minor=${ver#*.}
    if [[ $ver_major -gt $PYTHON_MIN_MAJOR ]] || \
       [[ $ver_major -eq $PYTHON_MIN_MAJOR && $ver_minor -ge $PYTHON_MIN_MINOR ]]; then
      PYTHON_BIN=$(command -v "$candidate")
      ok "找到 $PYTHON_BIN (Python $ver)"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  fail "未找到 Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+. 请先安装 (apt install python3.12-venv 或 pyenv)."
fi

# ─── 创建 venv ────────────────────────────────────────────────────
if [[ $RECREATE -eq 1 && -d "$VENV_DIR" ]]; then
  warn "删除现有 $VENV_DIR"
  rm -rf "$VENV_DIR"
fi

if [[ ! -d "$VENV_DIR" ]]; then
  log "创建 venv 于 $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  ok "venv 已创建"
else
  ok "venv 已存在,跳过创建"
fi

# 在脚本内激活
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ─── 升级 pip ─────────────────────────────────────────────────────
log "升级 pip"
python -m pip install --quiet --upgrade pip

# ─── 装包 ─────────────────────────────────────────────────────────
log "安装 dock-guard${EXTRAS} (editable)"
if [[ -n "$EXTRAS" ]]; then
  python -m pip install -e ".${EXTRAS}"
else
  python -m pip install -e .
fi
ok "依赖安装完成"

# ─── 可选: 复制 config 模板 ────────────────────────────────────────
if [[ $COPY_CONFIG -eq 1 ]]; then
  log "复制 *.yaml.example -> *.yaml (仅当目标不存在)"
  for example in config/*.yaml.example; do
    target="${example%.example}"
    if [[ ! -e "$target" ]]; then
      cp "$example" "$target"
      ok "  copied $target"
    else
      warn "  $target 已存在,跳过"
    fi
  done

  if [[ ! -e ".env" && -e ".env.example" ]]; then
    cp ".env.example" ".env"
    ok "  copied .env"
  elif [[ -e ".env" ]]; then
    warn "  .env 已存在,跳过"
  fi
fi

# ─── 验证 ─────────────────────────────────────────────────────────
log "验证 CLI"
if python -m dock_guard --version >/dev/null 2>&1; then
  ok "$(python -m dock_guard --version)"
else
  fail "python -m dock_guard --version 失败"
fi

# ─── 完成 ─────────────────────────────────────────────────────────
echo
ok "Phase 0 安装完成"
echo
echo "下一步:"
echo "  1) 激活 venv:        ${C_INFO}source ${VENV_DIR}/bin/activate${C_END}"
if [[ $COPY_CONFIG -eq 0 ]]; then
  echo "  2) 复制配置模板:     ${C_INFO}./install.sh --copy-config${C_END}"
  echo "                       (或手动 cp config/*.yaml.example config/*.yaml)"
fi
echo "  3) 编辑配置:         ${C_INFO}vi .env${C_END}                     # 填 MQTT/钉钉/ADMIN_TOKEN"
echo "                       ${C_INFO}vi config/runtime.yaml${C_END}      # 填 dock_sn"
echo "                       ${C_INFO}vi config/dingtalk_robots.yaml${C_END}"
echo "  4) 试运行 (帮助):    ${C_INFO}python -m dock_guard --help${C_END}"
echo "  5) 离线回放验证:     ${C_INFO}python -m dock_guard --replay \\${C_END}"
echo "                       ${C_INFO}  ../sim_dji_cloud_service/sim_dji_cloud/recordings/8UUXN7N00A0GAA_20260605-165145/${C_END}"
echo
