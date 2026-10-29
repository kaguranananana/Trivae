# Evaluation workspace storage lifecycle

Date: 2026-10-29

## Implementation

- Formal `trivae eval run` now takes the validated master `freeze.json`. It creates a unique workspace under that freeze, clones Canonical and optional semantic databases with macOS `clonefile`, and checks the freeze ID, manifest version, snapshot fingerprint, and Canonical/lexical/semantic revisions before and after cloning. The native clone call fails closed; this path does not use `cp -c`, whose local macOS man page says it falls back to `copyfile(2)` when cloning is unavailable.
- The workspace is held by a filesystem lease. Application, Conversation, Trace, feedback, and temporary database files all stay inside it; the formal Evaluation DB defaults to `record-dir/evaluation.sqlite3`. Run and Result are committed by the Evaluation Store. Before closing the Application, the CLI atomically exports Run JSON and all referenced Trace projections. It then writes the terminal experiment manifest, closes SQLite connections, and removes the temporary databases.
- A persisted ordinary failure is recorded and cleaned. An interruption keeps its isolated workspace for seven days so a partial Trace or in-flight state can be recovered. A crash leaves an expired lease that the next managed run or `eval cleanup-workspaces` can reap. Reaping checks the workspace marker and lease, skips active processes, and only removes directories below the selected freeze's managed workspace root. `--keep-workspace` explicitly retains a debug copy for the same retention period.
- `create_application` cannot safely share a frozen database: Canonical Store switches to WAL and initializes/migrates schema; Semantic Index switches to WAL and initializes schema; Conversation, Trace, Evaluation, and feedback stores also initialize writable schemas. The composition root now rejects a Canonical or semantic path named as a master in its adjacent freeze manifest before opening writable stores. Direct SQLite consumers that open the freeze with `mode=ro` and do not initialize stores can share it; experiments that alter indexes or tables still need independent working data. Existing script-level `cp -c` use was left intact.
- Long-term storage and usage guidance is in `AGENTS.md`, `docs/evaluation.md`, and `docs/evaluation-langsmith.md`.

## Disk measurement

Used the existing validated master freeze `freeze-84892e107a4548bc849a60ebed7c9314` with snapshot `snapshot-v1:messages=864615:first=1753011800000:last=1793108691000:sources=206:lexical={'present': True, 'message_count': 881236}`. It contains 3,786,088,448 logical database bytes. The measurement made an old-style SQLite backup into a temporary directory, measured it, removed only that generated directory, then made a managed APFS clone, opened and closed `create_application` on the clone without a model request, and let the workspace clean itself up.

| Measurement | `du -A` logical size | `df` available space |
| --- | ---: | ---: |
| Before temporary copies | — | 22.308 GiB |
| SQLite backup working copy | 3,697,353 KiB | 18.762 GiB (down 3.546 GiB) |
| After removing that generated copy | — | 22.295 GiB |
| APFS clone before application initialization | 3,697,677 KiB | 22.295 GiB (change under 1 MiB from prior reading) |
| APFS clone after application initialization | — | 22.293 GiB (about 2 MiB less available) |
| After managed cleanup | — | 22.296 GiB |

The `du -A` size remains about 3.526 GiB because it reports the full logical contents of the clone. The SQLite backup reduced free space by 3.546 GiB. The APFS clone plus application initialization changed available space by roughly 2 MiB while present, within the `df` movement observed around deletion and measurement; after cleanup there was no lasting multi-gigabyte growth. This demonstrates about 3.5 GiB avoided per full-size working database set on this snapshot. System and filesystem activity account for the small differences between readings.

The benchmark used the actual 3.5 GiB freeze, not model inference. No historical result, master database, or freeze was removed. Only the generated backup and the generated managed workspace were deleted.

## Validation and limits

- Full `pytest`: 1391 passed, 1 skipped. The targeted evaluation and CLI subset was 79 passed.
- Full `ruff check src tests scripts`, Mypy on all 148 source files, and `git diff --check`: passed.
- Workspace tests cover normal cleanup, persisted runtime failure, interruption recovery and expiry, explicit retention, parallel isolation, manifest version mismatch, no regular-copy fallback, and a symlink cleanup boundary. The formal CLI test confirms Run/Trace persistence precedes cleanup.
- This is macOS APFS-specific by design. On another filesystem or when `clonefile` fails, cloning reports an error; there is no full-copy fallback. The existing deterministic snapshot identity follows current Trivae metadata/source contracts and does not introduce a content hash. Handwritten experiment scripts gain automatic cleanup only when they use `EvaluationWorkspace`; direct `create_application` calls remain the script author's responsibility. The unified formal CLI path enforces the lifecycle.
