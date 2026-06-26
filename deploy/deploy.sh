#!/usr/bin/env bash
set -euo pipefail

# 一键部署到腾讯云 SCF（Web 函数 + API 网关 + 每日 Timer）。
#
# 依赖太大装不进函数代码包（SCF 限制），故采用 Layer 方案：
#   - 依赖打成 Layer（挂载到 /opt/python），自动上传 COS 并发布层版本；
#   - 函数代码包只含 app/（极小）。
#
# 用法:
#   1. export 好机密（见 deploy/.env / 下方 REQUIRED）
#   2. bash deploy/deploy.sh
#
# 依赖: docker、components(@serverless/components)、python3+venv、rsync、zip、openssl
#   注意: 腾讯 SCF 组件需用 @serverless/components 引擎（npm i -g @serverless/components）
#   + SLS_GEO_LOCATION=no-cn；serverless v3/v4 均不可用。

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/deploy/.run"
LAYER_SRC="$WORK/layer"          # layer/python/<deps>
BUILD="$WORK/build"              # 仅代码
VENV="$ROOT/server/.venv"
REGION="${SCF_REGION:-ap-shanghai}"
LAYER_NAME="${LAYER_NAME:-pusher-deps}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 1. 前置检查 ----
for bin in docker components rsync zip openssl python3; do
  command -v "$bin" >/dev/null 2>&1 || die "缺少依赖: $bin"
done
docker info >/dev/null 2>&1 || die "Docker 未运行，请先启动 Docker。"
[ -x "$VENV/bin/python" ] || die "缺少 venv: $VENV（先在 server/ 建 .venv）"

REQUIRED=(MYSQL_HOST MYSQL_USER MYSQL_PASSWORD MYSQL_DATABASE
          TENCENT_SECRET_ID TENCENT_SECRET_KEY)
missing=()
for v in "${REQUIRED[@]}"; do [ -n "${!v:-}" ] || missing+=("$v"); done
[ ${#missing[@]} -eq 0 ] || die "缺少环境变量: ${missing[*]}"

# 可选项默认值
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
export TIMER_SECRET="${TIMER_SECRET:-$(openssl rand -hex 16)}"
log "TIMER_SECRET = $TIMER_SECRET （已注入函数环境变量与 Timer argument）"

# 内网数据库可选 VPC 绑定（注意绑定后需为函数另配公网出口/NAT）
export VPC_ID="${VPC_ID:-}"
export SUBNET_ID="${SUBNET_ID:-}"
if { [ -n "$VPC_ID" ] && [ -z "$SUBNET_ID" ]; } || { [ -z "$VPC_ID" ] && [ -n "$SUBNET_ID" ]; }; then
  die "VPC_ID 与 SUBNET_ID 必须同时设置。"
fi

# ---- 2. 构建依赖层（trim 后约 200MB，含 python/ 目录）----
log "清理工作目录: $WORK"
rm -rf "$WORK"; mkdir -p "$LAYER_SRC/python" "$BUILD"

log "在 python:3.10-slim 容器内安装依赖并精简（strip .so / 去 pytest / 删 tests）"
docker run --rm --platform linux/amd64 \
  -v "$LAYER_SRC":/layer \
  -v "$ROOT/server/requirements.txt":/req.txt:ro \
  -w /layer python:3.10-slim bash -c '
    set -e
    apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y binutils >/dev/null 2>&1
    pip install --no-cache-dir -r /req.txt -t /layer/python
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

log "打包 layer.zip"
( cd "$LAYER_SRC" && zip -r -q -X "$WORK/layer.zip" python )

# ---- 3. 上传 COS + 发布层版本 ----
log "确保本机 venv 有 COS/SCF SDK"
"$VENV/bin/pip" install -q cos-python-sdk-v5 tencentcloud-sdk-python-scf 2>&1 | tail -1 || true

log "上传依赖层到 COS 并发布层版本…"
export SCF_REGION="$REGION" LAYER_ZIP="$WORK/layer.zip" LAYER_NAME
LAYER_VERSION="$("$VENV/bin/python" "$ROOT/deploy/publish_layer.py" | sed -n 's/^LAYER_VERSION=//p')"
[ -n "$LAYER_VERSION" ] || die "发布 Layer 失败（见上方日志）"
log "Layer: ${LAYER_NAME} 版本 ${LAYER_VERSION}"

# ---- 4. 构建“仅代码”函数包 ----
log "复制应用代码（不含依赖）"
rsync -a \
  --exclude 'tests' --exclude '__pycache__' --exclude '.venv' --exclude '*.pyc' \
  "$ROOT/server/" "$BUILD/"
chmod +x "$BUILD/scf_bootstrap"

# ---- 5. 生成 serverless.yml（引用 Layer；机密用 ${env:...} 注入，不落盘）----
log "生成 $WORK/serverless.yml"
cat > "$WORK/serverless.yml" <<'YML'
component: scf
name: pusher-go-advanced
inputs:
  name: pusher-go-advanced
  src:
    src: ./build
    exclude:
      - '**/__pycache__/**'
  handler: scf_bootstrap
  runtime: Python3.10
  region: __REGION__
  memorySize: 1024
  timeout: 600
  type: web
  layers:
    - name: __LAYER_NAME__
      version: __LAYER_VERSION__
  environment:
    variables:
      MYSQL_HOST: ${env:MYSQL_HOST}
      MYSQL_PORT: ${env:MYSQL_PORT}
      MYSQL_USER: ${env:MYSQL_USER}
      MYSQL_PASSWORD: ${env:MYSQL_PASSWORD}
      MYSQL_DATABASE: ${env:MYSQL_DATABASE}
      DEEPSEEK_API_KEY: ${env:DEEPSEEK_API_KEY}
      KIMI_API_KEY: ${env:KIMI_API_KEY}
      KIMI_ENDPOINT: ${env:KIMI_ENDPOINT}
      DEEPSEEK_MODEL: ${env:DEEPSEEK_MODEL}
      PLANNER_MODEL: ${env:PLANNER_MODEL}
      ANALYST_MODEL: ${env:ANALYST_MODEL}
      REVIEWER_MODEL: ${env:REVIEWER_MODEL}
      EMAIL_SMTP_HOST: ${env:EMAIL_SMTP_HOST}
      EMAIL_SMTP_PORT: ${env:EMAIL_SMTP_PORT}
      EMAIL_FROM: ${env:EMAIL_FROM}
      EMAIL_PASSWORD: ${env:EMAIL_PASSWORD}
      TIMER_SECRET: ${env:TIMER_SECRET}
  events:
    - apigw:
        parameters:
          protocols:
            - https
          endpoints:
            - path: /
              method: ANY
    - timer:
        parameters:
          name: daily-pipeline
          cronExpression: "0 0 8 * * * *"
          enable: true
          argument: ${env:TIMER_SECRET}
YML
sed -i.bak \
  -e "s/__REGION__/${REGION}/" \
  -e "s/__LAYER_NAME__/${LAYER_NAME}/" \
  -e "s/__LAYER_VERSION__/${LAYER_VERSION}/" \
  "$WORK/serverless.yml" && rm -f "$WORK/serverless.yml.bak"

if [ -n "$VPC_ID" ]; then
  log "绑定 VPC: ${VPC_ID} / ${SUBNET_ID}"
  awk -v vpc="$VPC_ID" -v sub="$SUBNET_ID" '
    {print}
    /^  type: web$/ { print "  vpcConfig:"; print "    vpcId: " vpc; print "    subnetId: " sub }
  ' "$WORK/serverless.yml" > "$WORK/serverless.yml.tmp" && mv "$WORK/serverless.yml.tmp" "$WORK/serverless.yml"
fi

# ---- 6. 部署 ----
log "components deploy（区域 ${REGION}）…"
( cd "$WORK" && SLS_GEO_LOCATION=no-cn components deploy )

log "部署完成。"
cat <<EOF

下一步烟测（把 <apigw-host> 换成上面输出的 API 网关地址）:
  curl https://<apigw-host>/health        # 期望 {"status":"ok"}

  export PUSHER_ENDPOINT=https://<apigw-host>
  pusher register --email you@example.com
  pusher portfolio add-stock 600519 --quantity 100
  pusher trigger run
  pusher report today
EOF
