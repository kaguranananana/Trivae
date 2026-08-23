# Implementation Plan

1. Read the baseline contracts and existing CLI/test patterns; record exact Application, QueryRequest, ExecutionScope, Session metadata, QueryResult, Trace and Settings APIs.
2. Implement the smallest public session-list read facade if required, returning existing session metadata without direct SQLite access from the CLI.
3. Add `chat` parsing and an interactive loop with:
   - session selection including unrestricted scope;
   - independent `selected_session_id`/scope and `conversation_id` state;
   - formal `QueryRequest` construction and `await application.query()`;
   - final answer, trace ID, `/new`, `/exit`, `/quit`, EOF and Ctrl+C behavior.
4. Add deterministic tests with no real provider call; preserve tests for import, trace and evaluation parser behavior.
5. Run focused tests, then `pytest`, `ruff check .`, and `mypy src`; investigate failures at their root.
6. If configured, run a real two-question smoke test against the checked-in database and DeepSeek environment; otherwise report the exact missing prerequisite.
7. Review diff for scope, Chinese code comments on generated code, and update task evidence before commit.
