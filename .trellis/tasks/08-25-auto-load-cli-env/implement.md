# Implementation plan

1. Add the typed dotenv parser/injector under `src/trivae/config/` with simplified Chinese comments for key logic.
2. Add `chat --env-file`, load the file before Application construction, and map dotenv errors to the existing CLI error boundary.
3. Add focused tests for parsing, precedence, explicit failures, and parser wiring.
4. Update backend runtime, quality, and Product Experience specs with the new startup contract.
5. Run focused tests, full test suite, lint/type checks available in the repository, and the real no-manual-source startup smoke.
6. Review the diff for secret exposure and unrelated changes, then commit and archive the Trellis task.
