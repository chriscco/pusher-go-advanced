#!/usr/bin/env bash
set -euo pipefail

# 一键部署到腾讯云 SCF（Web 函数 + API 网关 + 每日 Timer）。
#
# 与 build_layer.sh + serverless.yml 的「依赖层」方案不同，本脚本把依赖
# 直接打进函数包（与 app/ 同级，scf_bootstrap 已把 /var/user 加入
# PYTHONPATH），因此无需在控制台手动建层、上传 layer.zip —— 真正一键。
#
# 用法:
#   1. export 好机密（见下方 REQUIRED / 可选默认值）
#   2. bash deploy/deploy.sh
#
# 依赖: docker、serverless(Serverless Framework)、rsync、openssl

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/deploy/.run"
BUILD="$WORK/build"
REGION="${SCF_REGION:-ap-guangzhou}"

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m错误:\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 1. 前置检查 ----
for bin in docker serverless rsync openssl; do
  command -v "$bin" >/dev/null 2>&1 || die "缺少依赖: $bin"
done
docker info >/dev/null 2>&1 || die "Docker 未运行，请先启动 Docker。"

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
# 未提供则自动生成一个 Timer 密钥
export TIMER_SECRET="${TIMER_SECRET:-$(openssl rand -hex 16)}"
log "TIMER_SECRET = $TIMER_SECRET （已注入函数环境变量与 Timer argument）"

# 若数据库走内网（如 TDSQL-C 只暴露内网地址），需把函数绑定到同一 VPC/子网。
# 设置 VPC_ID 与 SUBNET_ID 即自动注入 vpcConfig。
# 注意: 绑定 VPC 后函数默认无公网出口，需另行为函数开启「公网访问」或挂 NAT，
#       否则 DeepSeek / yfinance / SMTP / RSS 等外网调用会超时。
export VPC_ID="${VPC_ID:-}"
export SUBNET_ID="${SUBNET_ID:-}"
if { [ -n "$VPC_ID" ] && [ -z "$SUBNET_ID" ]; } || { [ -z "$VPC_ID" ] && [ -n "$SUBNET_ID" ]; }; then
  die "VPC_ID 与 SUBNET_ID 必须同时设置。"
fi

# ---- 2. 构建自带依赖的部署包 ----
log "清理并准备构建目录: $WORK"
rm -rf "$WORK"
mkdir -p "$BUILD"

log "复制应用代码（排除 tests/缓存）"
rsync -a \
  --exclude 'tests' --exclude '__pycache__' --exclude '.venv' --exclude '*.pyc' \
  "$ROOT/server/" "$BUILD/"

log "在 python:3.10-slim 容器内安装依赖到包根目录（与 SCF 运行时对齐）"
docker run --rm \
  -v "$BUILD":/pkg \
  -v "$ROOT/server/requirements.txt":/req.txt:ro \
  -w /pkg python:3.10-slim \
  bash -c "pip install --no-cache-dir -r /req.txt -t ."

chmod +x "$BUILD/scf_bootstrap"

# ---- 3. 生成 serverless 配置（无 layer；机密用 \${env:...} 注入，不落盘）----
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
# 仅替换非机密的 region 占位符（机密保持 ${env:...} 由 serverless 读取）
sed -i.bak "s/__REGION__/${REGION}/" "$WORK/serverless.yml" && rm -f "$WORK/serverless.yml.bak"

# 内网数据库：把函数绑定到同一 VPC/子网
if [ -n "$VPC_ID" ]; then
  log "绑定 VPC: ${VPC_ID} / ${SUBNET_ID}"
  awk -v vpc="$VPC_ID" -v sub="$SUBNET_ID" '
    {print}
    /^  type: web$/ {
      print "  vpcConfig:"
      print "    vpcId: " vpc
      print "    subnetId: " sub
    }' "$WORK/serverless.yml" > "$WORK/serverless.yml.tmp" \
    && mv "$WORK/serverless.yml.tmp" "$WORK/serverless.yml"
fi

# ---- 4. 部署 ----
log "serverless deploy（区域 ${REGION}）…"
( cd "$WORK" && serverless deploy )

log "部署完成。"
cat <<EOF

下一步烟测（把 <apigw-host> 换成上面输出的 API 网关地址）:
  curl https://<apigw-host>/health        # 期望 {"status":"ok"}

  export PUSHER_ENDPOINT=https://<apigw-host>
  pusher register --email you@example.com
  pusher portfolio add-stock 600519 --quantity 100
  pusher trigger run
  pusher report today

提醒:
  - 数据库需自行创建并应用 sql/schema.sql（内网库可用 DMC 控制台或临时外网地址执行）。
  - 安全组放行函数所在子网访问 3306。
  - 若已绑定 VPC（设置了 VPC_ID/SUBNET_ID），记得为函数开启「公网访问」或挂 NAT，
    否则 DeepSeek / yfinance / SMTP / RSS 等外网调用会超时。
EOF
