"""Q8 step1: temporal_or_scope_error distribution across the 64 A/B runs + prompt surface check.

Prompt check (manual, recorded here): SYSTEM_PROMPT (src/trivae/query/runtime/prompt.py:14-314)
read in full on branch research/agent-quality-20261029 — time rules are retrieval-window
selection (:16-30, :117-121) and timestamp-copying rules (:308-313); there is NO answer-layer
requirement to state that historical messages cannot confirm validity at query time.
Experiment prompt variants prompts/A.txt (296 lines) / prompts/B.txt (300 lines) also lack it
(grep for valid/current/still/no longer/may have changed returns only retrieval-window and
citation-handle rules). Dynamic instructions had no such anchor either (verified in the
integration round: openai_adapter.py:1648-1689).
"""
import json
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/anontokyo/Downloads/Project/Learn/Trivae")
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
OUT = ROOT / "research/agent-quality-20261029/rounds/outputs"
d = json.load(open(BASE / "study-data.json"))

rows = []
by_arm = Counter()
by_case = Counter()
severity = Counter()
for cid, c in d["cases"].items():
    for arm, rlist in c["runs"].items():
        for i, r in enumerate(rlist):
            diag = r.get("review_diagnostics") or []
            terr = [x for x in diag if isinstance(x, dict) and "temporal" in json.dumps(x)]
            if not terr:
                continue
            ncite = len(r.get("answer_cited_messages") or [])
            ans = r.get("answer_text") or ""
            form = ("no_result" if ans.strip().startswith("{") and "no_result" in ans[:200]
                    else ("insufficient" if "insufficient_evidence" in ans[:300] else "claims"))
            by_arm[arm] += len(terr)
            by_case[cid] += len(terr)
            for x in terr:
                severity[x.get("severity")] += 1
            rows.append({"case": cid, "arm": arm, "idx": i, "n_err": len(terr),
                         "citations": ncite, "form": form})

out = {
    "total_temporal_errors": sum(by_arm.values()),
    "by_arm": dict(by_arm),
    "n_runs_with_errors": len(rows),
    "n_runs_total": sum(len(rr) for c in d["cases"].values() for rr in c["runs"].values()),
    "by_case": dict(by_case),
    "severity": dict(severity),
    "runs_with_citations": sum(1 for x in rows if x["citations"] > 0),
    "form_counter": dict(Counter(x["form"] for x in rows)),
    "rows": rows,
}
json.dump(out, open(OUT / "q8-temporal.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False, indent=1))
