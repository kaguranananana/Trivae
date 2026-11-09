---
name: project-memory
description: "Trivae: read current development state when switching agents, and record substantive implementation or evaluation progress with verifiable results. No coding workflow gates."
---

# Trivae project memory

When resuming after a context switch:
- Read docs/PROJECT_STATUS.md and recent docs/DEVLOG.md entries as needed.
- Verify current behavior against source and tests. Consult old .trellis/workspace/anontokyo/ journals, .trellis/tasks/ and .trellis/spec/ only for relevant history.

After meaningful implementation, debugging or evaluation:
- Append a brief dated entry to docs/DEVLOG.md: relevant files, real change, actual tests/checks and results, notable decisions and next steps.
- Update docs/PROJECT_STATUS.md only when its summary changes. Keep operating details in the relevant current guide and preserve dated decisions and evidence in their historical context.
- Never invent validation, results or decisions. Do not create new journal entries for casual Q&A or insignificant edits.

No Trellis phases, PRDs, mandatory planning questions, automatic sub-agent dispatch or approval gates.
