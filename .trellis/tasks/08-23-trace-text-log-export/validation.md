# Validation

## Passed

- `python3 -m compileall -q src tests`
- `git diff --check`
- `./.venv/bin/pytest` → 169 passed
- `./.venv/bin/ruff check src tests` → passed
- `./.venv/bin/mypy src` → passed
- `./.venv/bin/trivae trace show trace-e90127d43d6d416e92d9d2f7ef53d70b --database data/trivae.sqlite3` → existing JSON Trace projection still readable
- `./.venv/bin/trivae trace export ... --database data/trivae.sqlite3` → six real Trace text logs generated under `data/traces/`

## Known repository-wide check

- `./.venv/bin/ruff check .` 仍被 `.codex/hooks` 和 `.trellis/scripts` 中的既有 lint 问题阻断；本次变更未修改这些目录。变更范围内的 `ruff check src tests` 已通过。

## Real Trace migration

已从 `data/trivae.sqlite3` 导出以下六条已有 Trace：

- `trace-657b26317b0b4346be4a417b01cc1f58`
- `trace-eb0d663162a64ad1a4242f8af432931e`
- `trace-bbbd84cb27db49d0b33f0479204842db`
- `trace-e90127d43d6d416e92d9d2f7ef53d70b`
- `trace-e34ad85fdbdf4b8da92df0febf2670e0`
- `trace-aca0aff848604533a25b5f407804c3c5`

日志文件位于默认 `data/traces/`，被 `.gitignore` 的 `*.log` 规则忽略，不进入提交。
