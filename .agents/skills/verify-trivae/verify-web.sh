#!/usr/bin/env bash
# Independent, explicit browser E2E; never invoked by regular pytest or verify.sh.
set -euo pipefail
cd "$(dirname "$0")/../../.."
mkdir -p data/evaluation/verify-trivae

evidence=$(mktemp -d "$PWD/data/evaluation/verify-trivae/browser.XXXXXX")
scratch=$(mktemp -d "${TMPDIR:-/tmp}/trivae-browser.XXXXXX")
server_pid=""
cleanup() {
    if [[ -n "$server_pid" ]]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    rm -rf -- "$scratch"
    echo "Removed scratch: $scratch"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
echo "Evidence: $evidence"

chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[[ -x "$chrome" ]] || { echo "Chrome not found: $chrome" >&2; exit 2; }
[[ -d web/node_modules/playwright-core ]] || { echo "Run pnpm -C web install --frozen-lockfile first" >&2; exit 2; }
command -v pnpm >/dev/null || { echo "pnpm not installed" >&2; exit 2; }
# Build BEFORE FastAPI starts: create_web_app discovers the static directory at startup.
# This also works on a fresh clone without an existing web/dist.
if ! pnpm -C web build > "$evidence/build.log" 2>&1; then
    echo "Frontend build failed; see $evidence/build.log" >&2; exit 1
fi
port=$(.venv/bin/python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
if [[ "${1:-}" == "--negative-control" ]]; then
    set -- --invalid-citation
elif [[ $# -gt 0 ]]; then
    echo "Usage: verify-web.sh [--negative-control]" >&2; exit 2
else
    set --
fi
# Never read the project dotenv file or real chat data. No external LLM requests.
env -u OPENAI_API_KEY -u DEEPSEEK_API_KEY -u OPENROUTER_API_KEY \
    uv run --offline --no-sync --no-env-file python \
    .agents/skills/verify-trivae/scripts/fixture_server.py --scratch "$scratch" --port "$port" "$@" \
    > "$evidence/server.log" 2>&1 &
server_pid=$!

ready=0
for ((i=0; i<100; i++)); do
    if curl --noproxy '*' --silent --fail --max-time 1 "http://127.0.0.1:$port/api/readiness" > "$evidence/readiness.json"; then
        ready=1
        break
    fi
    if ! kill -0 "$server_pid" 2>/dev/null; then break; fi
    sleep 0.2
done
if [[ "$ready" != 1 ]]; then
    echo "Fixture server not ready; see $evidence/server.log" >&2
    exit 1
fi

set +e
node .agents/skills/verify-trivae/scripts/browser_e2e.mjs "http://127.0.0.1:$port" "$evidence" "$chrome" \
    > "$evidence/browser.log" 2>&1
status=$?
set -e
cat "$evidence/browser.log"
echo "Browser E2E exit: $status"
exit "$status"
