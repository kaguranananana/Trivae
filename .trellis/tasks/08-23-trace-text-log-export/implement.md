# Implementation plan

## Ordered steps

1. Add Trace text formatter/writer with safe default path and deterministic event formatting.
2. Connect `SQLiteTraceStore` to incremental sidecar writes without changing SQLite facts or Query control flow.
3. Expose `TrivaeApplication.export_trace_log()` and add `trace export` CLI command.
4. Show the exported log path in the interactive chat loop, including explicit export failure diagnostics.
5. Add observability and CLI regression tests; keep import/trace/eval parser coverage.
6. Export the recent real Trace IDs from `data/trivae.sqlite3` into `data/traces/` and inspect the files.

## Validation

- `python3 -m compileall -q src tests`
- `./.venv/bin/pytest`
- `./.venv/bin/ruff check src tests`
- `./.venv/bin/mypy src`
- `git diff --check`
- `./.venv/bin/trivae trace export <trace_id> --database data/trivae.sqlite3`

## Risky files

- `src/trivae/observability/sqlite.py`: sidecar writes must remain derived and must not change SQLite Trace ordering.
- `src/trivae/interfaces/cli.py`: preserve existing import/trace/eval dispatch and thin Application boundary.
- `src/trivae/bootstrap/application.py`: new facade must only read/export existing Trace facts.
