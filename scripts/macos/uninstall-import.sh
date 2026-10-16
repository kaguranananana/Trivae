#!/bin/bash
# 停止失败必须立即暴露，不能伪装成已经卸载。
set -euo pipefail
# 从脚本位置定位项目，不依赖当前工作目录。
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Python 管理器只删除调度配置，保留原始记录、数据库及日志。
exec "${script_dir}/../../.venv/bin/python" "${script_dir}/launchd_import.py" uninstall "$@"
