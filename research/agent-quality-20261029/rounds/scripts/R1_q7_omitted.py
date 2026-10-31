"""Q7 (aggregate part): omitted-message counts and neighbor-hit saturation across the 42
new-agent run traces. GT-intersection and timestamp-skew parts are computed from the Q1
replay output (see R1_q7_gt.py after replay completes)."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path("/Users/anontokyo/Downloads/Project/Learn/Trivae")
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
OUT = ROOT / "research/agent-quality-20261029/rounds/outputs"
study = json.load(open(BASE / "study-data.json"))

agg = Counter()
omitted_by_tool = Counter()
per_run_omit = []
cs_hits = []
for cid, case in study["cases"].items():
    for arm, rlist in case["runs"].items():
        for r in rlist:
            if r["source"] != "new-agent-run":
                continue
            t = json.load(open(ROOT / r["trace"]["trace_path"]))
            run_omit = 0
            for e in t["timeline"]:
                if e["operation"] == "runtime.tool.completed":
                    p = e["payload"]
                    agg["calls"] += 1
                    agg["proj_total"] += p.get("projected_messages") or 0
                    oh = p.get("omitted_hit_messages") or 0
                    oc = p.get("omitted_context_messages") or 0
                    if oh or oc:
                        agg["calls_with_omit"] += 1
                        agg["omit_total"] += oh + oc
                        omitted_by_tool[p.get("tool_name")] += oh + oc
                        run_omit += oh + oc
                    if p.get("projection_truncated"):
                        agg["calls_truncated"] += 1
                elif e["operation"] == "retrieval.search.completed":
                    d2 = (e["payload"].get("context_expansion") or e["payload"]) or {}
                    det = d2.get("details") or d2
                    csh = det.get("context_source_hits")
                    if csh is not None:
                        cs_hits.append({"case": cid, "arm": arm, "strategy": e["payload"].get("strategy"),
                                        "context_source_hits": csh})
            if run_omit:
                per_run_omit.append({"case": cid, "arm": arm, "omitted": run_omit})

out = {
    "n_tool_calls": agg["calls"],
    "n_calls_with_omission": agg["calls_with_omit"],
    "n_calls_projection_truncated": agg["calls_truncated"],
    "projected_messages_total": agg["proj_total"],
    "omitted_messages_total": agg["omit_total"],
    "omitted_by_tool": dict(omitted_by_tool),
    "n_runs_with_any_omission": len(per_run_omit),
    "top_runs_by_omission": sorted(per_run_omit, key=lambda x: -x["omitted"])[:10],
    "context_source_hits_distribution": dict(Counter(x["context_source_hits"] for x in cs_hits)),
    "context_source_hits_saturated_at_20": sum(1 for x in cs_hits if x["context_source_hits"] == 20),
    "n_retrieval_calls_with_csh_recorded": len(cs_hits),
}
json.dump(out, open(OUT / "q7-omitted.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
