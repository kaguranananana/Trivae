#!/bin/bash
# 状态查询失败时保留非零退出码，不隐藏 launchctl 的错误。
set -euo pipefail
# 从脚本位置定位项目，不依赖当前工作目录。
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# 状态脚本只查询任务，导入状态另用 import-once --status 查看。
exec "${script_dir}/../../.venv/bin/python" "${script_dir}/launchd_import.py" status "$@"
