#!/bin/bash
# 任何路径解析或 Python 启动失败均立即退出，保留原始错误。
set -euo pipefail
# 从脚本位置定位项目，使调用者可以从任意目录执行。
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# 直接使用项目虚拟环境，避免 launchd 和终端的 PATH 差异。
exec "${script_dir}/../../.venv/bin/python" "${script_dir}/launchd_import.py" install "$@"
