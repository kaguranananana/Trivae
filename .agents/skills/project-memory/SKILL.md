---
name: project-memory
description: "Trivae: read current development state when switching agents, and record substantive implementation or evaluation progress with verifiable results. No coding workflow gates."
---

# Trivae project memory

When resuming after a context switch:
- Read docs/PROJECT_STATUS.md and recent docs/DEVLOG.md entries as needed.
- For detail, inspect old .trellis/workspace/anontokyo/ journals, .trellis/tasks/, .trellis/spec/, Git and code. Verify important current-state claims against code.

After meaningful implementation, debugging or evaluation:
- Update docs/PROJECT_STATUS.md with confirmed done / in-progress / blocked / next.
- Append a brief dated entry to docs/DEVLOG.md: relevant files, real change, actual tests/checks and results, notable decisions and next steps.
- Persist lasting, non-obvious contracts/decisions into an appropriate .trellis/spec/ document only when useful.
- Never invent validation, results or decisions. Do not create new journal entries for casual Q&A or insignificant edits.

No Trellis phases, PRDs, mandatory planning questions, automatic sub-agent dispatch or approval gates.
