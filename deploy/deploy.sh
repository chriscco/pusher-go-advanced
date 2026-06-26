#!/usr/bin/env bash
set -euo pipefail

# 一键部署到腾讯云 SCF —— 每日日报（Event 函数 + Timer）。
#
# 背景：该账号 API 网关已停售、HTTP 函数不能挂 timer、serverless 组件不可用，
# 故直接用 SCF SDK 部署。每日流水线 = Event 函数 pusher-pipeline + 每日 Timer。
# 依赖打成 Layer（/opt/python），函数代码包只含 app/。
#
# 用法:
#   1. source deploy/.env   （或自行 export 机密，见下方 REQUIRED）
#   2. bash deploy/deploy.sh
#
# 依赖: docker、python3+server/.venv、rsync、zip、openssl

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/deploy/.run"
LAYER_SRC="$WORK/layer"          # layer/python/<deps>
BUILD="$WORK/build"              # 仅代码
VENV="$ROOT/server/.venv"
PY="$VENV/bin/python"
REGION="${SCF_REGION:-ap-shanghai}"
LAYER_NAME="${LAYER_NAME:-pusher-deps}"
FUNCTION_NAME="${FUNCTION_NAME:-pusher-pipeline}"
API_FUNCTION_NAME="${API_FUNCTION_NAME:-pusher-go-advanced}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 1. 前置检查 ----
for bin in docker rsync zip openssl python3; do
  command -v "$bin" >/dev/null 2>&1 || die "缺少依赖: $bin"
done
docker info >/dev/null 2>&1 || die "Docker 未运行，请先启动 Docker。"
[ -x "$PY" ] || die "缺少 venv: $VENV（先在 server/ 建 .venv 并装依赖）"

REQUIRED=(MYSQL_HOST MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE
          TENCENT_SECRET_ID TENCENT_SECRET_KEY)
missing=()
for v in "${REQUIRED[@]}"; do [ -n "${!v:-}" ] || missing+=("$v"); done
[ ${#missing[@]} -eq 0 ] || die "缺少环境变量: ${missing[*]}"

# 可选项默认值（函数运行期读取）
export MYSQL_PORT="${MYSQL_PORT:-3306}"
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"
export KIMI_API_KEY="${KIMI_API_KEY:-}"
export KIMI_ENDPOINT="${KIMI_ENDPOINT:-https://api.moonshot.cn/v1}"
export DEEPSEEK_MODEL="${DEEPSEEK_MODEL:-deepseek-chat}"
export PLANNER_MODEL="${PLANNER_MODEL:-deepseek-r1}"
export ANALYST_MODEL="${ANALYST_MODEL:-${DEEPSEEK_MODEL}}"
export REVIEWER_MODEL="${REVIEWER_MODEL:-${ANALYST_MODEL}}"
export EMAIL_SMTP_HOST="${EMAIL_SMTP_HOST:-}"
export EMAIL_SMTP_PORT="${EMAIL_SMTP_PORT:-587}"
export EMAIL_FROM="${EMAIL_FROM:-}"
export EMAIL_PASSWORD="${EMAIL_PASSWORD:-}"
# Timer 密钥：函数环境变量与触发器 CustomArgument 必须一致（本脚本同一次注入两处）
export TIMER_SECRET="${TIMER_SECRET:-$(openssl rand -hex 16)}"
log "TIMER_SECRET = $TIMER_SECRET"

# ---- 2. 构建依赖层（linux/amd64，trim 后约 200MB）----
log "清理工作目录: $WORK"
rm -rf "$WORK"; mkdir -p "$LAYER_SRC/python" "$BUILD"

log "在 python:3.10-slim (amd64) 内装依赖并精简（SCF 是 x86_64，必须 amd64）"
docker run --rm --platform linux/amd64 \
  -v "$LAYER_SRC":/layer \
  -v "$ROOT/server/requirements.txt":/req.txt:ro \
  -w /layer python:3.10-slim bash -c '
    set -e
    apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y binutils >/dev/null 2>&1
    pip install --no-cache-dir -r /req.txt -t /layer/python >/dev/null
    cd /layer/python
    rm -rf pytest _pytest pluggy iniconfig py pygments tomli
    find . -type d -name tests -prune -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
    find . -name "*.pyc" -delete 2>/dev/null || true
    find . -name "*.so*" -exec strip --strip-unneeded {} + 2>/dev/null || true
    # efinance 在包内硬写缓存目录；SCF 上 /opt 只读，改指 /tmp
    sed -i "s#DATA_DIR = HERE / \"../data\"#DATA_DIR = Path(\"/tmp/efinance_data\")#" \
      efinance/config/__init__.py 2>/dev/null || true
  '
log "依赖层大小: $(du -sh "$LAYER_SRC/python" | cut -f1)"
( cd "$LAYER_SRC" && zip -r -q -X "$WORK/layer.zip" python )

# ---- 3. 上传 COS + 发布层版本 ----
log "确保 venv 内有 COS/SCF SDK"
"$PY" -m pip install -q cos-python-sdk-v5 tencentcloud-sdk-python-scf 2>&1 | tail -1 || true

log "上传依赖层并发布层版本…"
export SCF_REGION="$REGION" LAYER_ZIP="$WORK/layer.zip" LAYER_NAME
LAYER_VERSION="$("$PY" "$ROOT/deploy/publish_layer.py" | sed -n 's/^LAYER_VERSION=//p')"
[ -n "$LAYER_VERSION" ] || die "发布 Layer 失败（见上方日志）"
log "Layer: ${LAYER_NAME} v${LAYER_VERSION}"

# ---- 4. 构建“仅代码”函数包 ----
log "复制应用代码（不含依赖）"
rsync -a --exclude 'tests' --exclude '__pycache__' --exclude '.venv' --exclude '*.pyc' \
  "$ROOT/server/" "$BUILD/"
chmod +x "$BUILD/scf_bootstrap"

# ---- 5a. 部署 Event 函数（日报流水线）+ 每日 Timer ----
export CODE_DIR="$BUILD" LAYER_VERSION
log "部署 Event 函数 ${FUNCTION_NAME} 并挂载每日 Timer…"
FUNCTION_NAME="$FUNCTION_NAME" FUNCTION_TYPE=Event \
  FUNCTION_HANDLER=scf_event_handler.main_handler \
  ENSURE_TIMER=1 TIMER_CRON="${TIMER_CRON:-0 0 8 * * * *}" \
  "$PY" "$ROOT/deploy/deploy_scf.py"

# ---- 5b. 部署 Web/API 函数（CLI 的 HTTP 接口，经函数 URL 暴露）----
# API 网关停售后用「函数 URL」暴露 Web 函数：scf_bootstrap 跑 uvicorn:9000。
# 函数 URL 需在控制台为该函数手动启用一次（授权类型选「开放」）；SDK 暂不支持开启，
# 但 deploy_scf.py 会读回 AccessInfo.Host 打印出 FUNCTION_URL。
log "部署 Web 函数 ${API_FUNCTION_NAME}（CLI HTTP API）…"
API_OUT="$(FUNCTION_NAME="$API_FUNCTION_NAME" FUNCTION_TYPE=HTTP \
  FUNCTION_HANDLER=scf_bootstrap ENSURE_TIMER=0 \
  "$PY" "$ROOT/deploy/deploy_scf.py" | tee /dev/stderr)"
API_URL="$(printf '%s\n' "$API_OUT" | sed -n 's/^FUNCTION_URL=//p' | head -1)"

log "部署完成。每日 08:00（北京）自动跑日报。"
echo
if [ -n "$API_URL" ]; then
  log "CLI HTTP API 地址（函数 URL）: ${API_URL}"
  cat <<EOF
把 CLI 指向它（写入 ~/.pusher/config.toml 的 server.endpoint，或用 --endpoint）:
  printf '[server]\nendpoint = "%s"\n\n[auth]\ntoken = ""\nemail = ""\n' "${API_URL}" > ~/.pusher/config.toml
然后:
  pusher register --email you@example.com
  pusher portfolio add-stock 600519 --quantity 100 --cost 1600
  pusher trigger run && pusher report today
EOF
else
  cat <<EOF
Web 函数已部署，但还没启用「函数 URL」。请在 SCF 控制台 → 函数 ${API_FUNCTION_NAME}
→ 启用「函数 URL」（授权类型选「开放」），然后重跑本脚本即可读回地址并接入 CLI。
EOF
fi
echo
cat <<EOF
手动触发日报一次（异步）并看结果:
  source deploy/.env
  "$PY" - <<'PYEOF'
import os, json
from tencentcloud.common import credential
from tencentcloud.scf.v20180416 import scf_client, models
cli = scf_client.ScfClient(credential.Credential(
    os.environ["TENCENT_SECRET_ID"], os.environ["TENCENT_SECRET_KEY"]), "${REGION}")
ir = models.InvokeRequest(); ir.FunctionName="${FUNCTION_NAME}"; ir.InvocationType="Event"
ir.ClientContext = json.dumps({"Type":"Timer","Message":os.environ["TIMER_SECRET"]})
print(cli.Invoke(ir).Result.FunctionRequestId)
PYEOF
  # 然后查 jobs/reports 表确认（运行约 5-6 分钟）
EOF
