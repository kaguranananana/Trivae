# Design: Automatic CLI dotenv loading

## Boundary

`interfaces.cli` owns startup orchestration. A small `config.dotenv` utility owns parsing and environment injection. `config.settings.load_settings()` remains a pure reader of the mapping it receives and is not changed to search the filesystem.

## Data flow

```text
CLI args -> config.dotenv (optional file parse) -> os.environ only for absent keys -> create_application -> load_settings -> readiness / Query
```

- `None` for `--env-file` means `Path.cwd() / ".env"`; a missing default file is allowed because the user may configure the process environment externally.
- An explicit path is required to exist and be a regular file. Read or parse failures are surfaced as a typed dotenv error.
- Parsing accepts blank lines, full-line comments, optional `export`, `KEY=VALUE`, and matching single/double quotes. It does not evaluate shell syntax or interpolation.
- Duplicate keys in the file use the last file assignment. Injection uses `os.environ.setdefault`, so a process value, including an empty one, always wins.
- The loader never returns or logs values. Error messages contain only path/line/format information.

## Compatibility and errors

- Existing non-chat commands do not load `.env` because they do not create a Provider-backed chat session through this startup path.
- A missing default `.env` preserves the current `SettingsError` when required Provider variables are absent.
- A malformed dotenv file fails before Application creation, making the configuration source and line number visible without masking the root cause.

## Verification

- Unit tests cover parser syntax, precedence, explicit missing file, malformed input, and CLI parser exposure.
- A real CLI smoke runs from the repository root with the four Provider variables removed from the process environment and stdin closed; readiness must report the Provider configured from `.env` without issuing a Query.
