#!/bin/bash
set -euo pipefail
# 在与 SCF 运行时一致的 Linux 环境构建依赖层（macOS 本机产物不可用于 SCF）。
# 用法: bash deploy/build_layer.sh

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/deploy/layer"
rm -rf "$OUT" && mkdir -p "$OUT/python"

docker run --rm -v "$ROOT":/work -w /work python:3.10-slim bash -c "
  pip install --no-cache-dir -r server/requirements.txt -t deploy/layer/python
"

cd "$OUT" && zip -r -q "$ROOT/deploy/layer.zip" python
echo "built: $ROOT/deploy/layer.zip"
