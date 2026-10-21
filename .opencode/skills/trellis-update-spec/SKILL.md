---
name: trellis-update-spec
description: "Optional: capture durable Trivae technical knowledge in existing docs; no mandatory template or task lifecycle."
---

# Durable project knowledge, only when useful

Use this skill when code, debugging, or evaluation reveals a long-lived and non-obvious fact: a public contract, significant technical decision with tradeoffs, or recurring failure pattern.

1. Read the affected code, tests and relevant existing .trellis/spec/ documents.
2. Update the smallest relevant existing document under .trellis/spec/project/ or .trellis/spec/backend/.
3. Distinguish verified behavior from hypotheses, and cite real files, tests or observed results where useful.
4. Keep the writing proportional. No seven-section requirement, mandatory PRD, task creation, second approval, phase gate, or forced sub-agent.
5. Routine progress belongs in docs/PROJECT_STATUS.md and docs/DEVLOG.md instead, not in a permanent spec.

This skill does not control implementation or require a write-up after every task.
