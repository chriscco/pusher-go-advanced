#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

TARGETS=(
  aarch64-apple-darwin
  x86_64-apple-darwin
  x86_64-unknown-linux-gnu
  x86_64-pc-windows-gnu
)

for t in "${TARGETS[@]}"; do
  echo "==> building $t"
  rustup target add "$t" || true
  cargo build --release --target "$t"
done

echo "done. binaries under cli/target/<target>/release/"
