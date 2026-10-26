#!/bin/bash
# 复用 Trivae 调度管理器；是否实际启用由调用者显式传入 --enable。
set -euo pipefail
QCE_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TRIVAE_PROJECT_DIR="$(cd "$QCE_SCRIPT_DIR/../.." && pwd)"
# 同一个 label 替换旧的纯入库调度，避免同时保留两套定时导出。
exec "$TRIVAE_PROJECT_DIR/.venv/bin/python" "$TRIVAE_PROJECT_DIR/scripts/macos/launchd_import.py" \
  install --qce-config "$QCE_SCRIPT_DIR/config.json" "$@"
