#!/usr/bin/env bash
# Opt-in real-provider smoke on isolated synthetic data. Never part of normal verify.
set -euo pipefail
cd "$(dirname "$0")/../../.."
mkdir -p data/evaluation/verify-trivae
if [[ "${1:-}" != "--run" || $# -ne 1 ]]; then
    echo "No provider called. To explicitly opt in:"
    echo '  TRIVAE_VERIFY_ALLOW_SPEND=YES TRIVAE_VERIFY_API_KEY=... TRIVAE_VERIFY_BASE_URL=https://... TRIVAE_VERIFY_PROVIDER=deepseek TRIVAE_VERIFY_MODEL=... .agents/skills/verify-trivae/verify-agent.sh --run'
    exit 0
fi
[[ "${TRIVAE_VERIFY_ALLOW_SPEND:-}" == "YES" ]] || { echo "Refusing to contact provider: explicit spend opt-in required" >&2; exit 2; }
evidence=$(mktemp -d "$PWD/data/evaluation/verify-trivae/agent.XXXXXX")
echo "Evidence: $evidence"
# Query-path smoke only; no dotenv read, no private chat source, one bounded case.
uv run --offline --no-sync --no-env-file python .agents/skills/verify-trivae/scripts/real_agent_smoke.py \
    > "$evidence/smoke.jsonl" 2>&1 || { cat "$evidence/smoke.jsonl"; exit 1; }
cat "$evidence/smoke.jsonl"
