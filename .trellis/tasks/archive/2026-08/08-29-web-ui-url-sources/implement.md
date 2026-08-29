# Implementation plan

## Phase 0 — planning gate

- [x] Read the project workflow, backend/project specifications, Web primary-interface decision, and related archived task records.
- [x] Audit the current Evidence URL extraction, snapshot hydration, Web projection, Markdown renderer, AssistantTurn wiring, SourcesBlock, and test setup.
- [x] Reproduce the URL false-positive and expanded-Sources behavior with focused local checks.
- [x] Record the confirmed contracts and failure cases in `prd.md` and `design.md`.
- [x] Obtain explicit approval of this planning summary before starting the Trellis task or editing product code.

## Phase 1 — regression tests first

- [x] Add backend extraction cases for Chinese/fullwidth boundaries, Markdown parentheses, query/fragment/percent escapes, adjacent Chinese text, duplicates, malformed URLs, non-HTTP(S), and the existing count/length bounds.
- [x] Add frontend renderer cases for exact trusted URLs, prefix/substring rejection, untrusted Markdown/autolinks, query/fragment/percent escapes, Chinese punctuation, code/fenced code, HTML disabling, and `target`/`rel`.
- [x] Add SourcesBlock interaction cases for initial collapsed state, expand/collapse, complete detail preservation, empty sources, independent instances, and fresh replay/remount defaults.
- [x] Run the new tests before product changes and retain the failing assertions as the regression baseline.

## Phase 2 — backend canonical URL extraction

- [x] Implement boundary-aware candidate scanning and explicit HTTP(S), host, port, and percent-escape validation in `src/trivae/query/evidence.py`.
- [x] Preserve the tuple return type, first-seen ordering, deduplication, `MAX_SOURCE_URLS`, and existing snapshot hydration/source-summary chain.
- [x] Run the focused Evidence tests and the existing provenance, scope, coverage, citation, hydration, and conversation tests.

## Phase 3 — Web trusted-link rendering and Sources UI

- [x] Replace unrestricted MarkdownIt linkification with token-level exact trusted URL matching in `web/src/utils/markdown.ts`; do not use final HTML regex replacement.
- [x] Include the trusted URL set in the renderer cache key and keep ordinary Markdown, code, HTML-disabled, and link attributes behavior intact.
- [x] Derive a deduplicated trusted URL set from `item.sources[].snapshot.urls` in `web/src/components/chat/AssistantTurn.vue`.
- [x] Add instance-local collapsed/expanded button state in `web/src/components/chat/SourcesBlock.vue` while preserving all existing source details and empty-list behavior.
- [x] Add only the test-only DOM dependencies/configuration required to exercise real component interaction, if the existing Web test setup cannot mount Vue components.

## Phase 4 — documentation and quality gate

- [x] Update the Web primary-interface decision with the trusted-link and collapsed-Sources contracts, including the precise Source semantics explanation.
- [x] Run Web unit tests, typecheck, lint, build, and the relevant Python test suites; fix implementation issues at their root without changing tests to hide failures.
- [x] Run `git diff --check` and inspect the final diff for scope, Simplified Chinese comments, and accidental Evidence/Citation contract changes.

## Phase 5 — real Web acceptance

- [x] Start the real `trivae web` path using the repository’s supported command and exercise Case A with a GitHub/resource canonical URL plus misleading adjacent prose.
- [x] Exercise Case B with a long answer and many Sources; verify initial collapsed state, expansion, complete details, re-collapse, and independent/replayed Assistant Turns.
- [x] Record fresh Trace IDs, commands, observations, and any environment/provider failure separately from code failures.
- [x] Complete the Trellis quality check and finish the task only after all required acceptance criteria are evidenced.

## Rollback points

- Backend extraction can be reverted independently from frontend rendering because the persisted snapshot/DTO shape remains unchanged.
- Frontend link rendering can be reverted independently from SourcesBlock state because Source selection and projection remain unchanged.
- Do not roll back by adding permissive linkification, source guessing, or silent error handling.
