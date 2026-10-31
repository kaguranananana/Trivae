"""Q9: A/B arm behavior-quantity comparison from study-data.json (64 runs)."""
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/anontokyo/Downloads/Project/Learn/Trivae")
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
OUT = ROOT / "research/agent-quality-20261029/rounds/outputs"
d = json.load(open(BASE / "study-data.json"))

agg = defaultdict(lambda: defaultdict(list))
per_case = {}
for cid, c in d["cases"].items():
    per_case[cid] = {"A": [], "B": []}
    for arm, runs in c["runs"].items():
        for r in runs:
            g = agg[arm]
            for k in ("tool_calls", "tool_rounds", "retrieval_count"):
                g[k].append(r.get(k))
            au = r.get("agent_usage") or {}
            for k in ("requests", "input_tokens", "output_tokens", "cached_input_tokens"):
                g[k].append(au.get(k))
            g["answer_len"].append(len(r.get("answer_text") or ""))
            es = r.get("evidence_sources") or {}
            entries = es.get("sources", []) if isinstance(es, dict) else es
            n_ev_ids = sum(len(e.get("message_ids") or []) for e in entries if isinstance(e, dict))
            g["evidence_items"].append(len(entries) if isinstance(entries, list) else 0)
            g["evidence_ids"].append(n_ev_ids)
            g["citations"].append(len(r.get("answer_cited_messages") or []))
            ans = r.get("answer_text") or ""
            g["digit_groups"].append(len(re.findall(r"\d+", ans)))
            g["urls"].append(len(re.findall(r"https?://", ans)))
            g["cjk_chars"].append(len(re.findall(r"[\u4e00-\u9fff]", ans)))
            g["diag_count"].append(len(r.get("review_diagnostics") or []))
            g["task"].append(r.get("task_satisfaction"))
            g["rel"].append(r.get("answer_reliability"))
            per_case[cid][arm].append({"tool_calls": r.get("tool_calls"), "task": r.get("task_satisfaction"),
                                       "rel": r.get("answer_reliability")})


def s(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 2) if xs else None


summary = {}
for k in agg["A"]:
    a, b = s(agg["A"][k]), s(agg["B"][k])
    summary[k] = {"A": a, "B": b, "B_over_A": round(b / a, 3) if a and b else None}
case_rows = {}
for cid, arms in per_case.items():
    ta = [x["task"] for x in arms["A"] if x["task"] is not None]
    tb = [x["task"] for x in arms["B"] if x["task"] is not None]
    ra = [x["rel"] for x in arms["A"] if x["rel"] is not None]
    rb = [x["rel"] for x in arms["B"] if x["rel"] is not None]
    case_rows[cid] = {
        "dTask": round(statistics.mean(tb) - statistics.mean(ta), 2) if ta and tb else None,
        "dRel": round(statistics.mean(rb) - statistics.mean(ra), 2) if ra and rb else None,
        "toolA": s([x["tool_calls"] for x in arms["A"]]),
        "toolB": s([x["tool_calls"] for x in arms["B"]]),
    }
out = {"arm_summary": summary, "per_case": case_rows}
json.dump(out, open(OUT / "q9-behavior.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
