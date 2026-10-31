"""Q5: run-level calibration of MODEL_TOKEN_CHAR_RATIO=3 (bytes/3) against provider tokens.

Per new-agent run (42):
  est_visible = (answer_text_bytes * M + tool_args_bytes) / 3
    - answer_text = concatenated claim texts (full, study-data content_blocks)
    - M = structural multiplier of the generated claims JSON (finding/criterion/sources/
      limitations/keys per claim), measured from each run's own trace output prefix where
      claim-1 is fully contained (trace truncates recorded text at 512 chars, so only the
      first claim is measurable); falls back to global median M.
    - tool_args = all tool-call argument strings from trace model.output (intact, <512 chars).
  actual_visible = agent_usage.output_tokens - agent_usage.reasoning_tokens
  ratio = actual_visible / est_visible   (>1 means bytes/3 UNDER-estimates tokens)

NOTE: a first-cut per-request pairing (output text vs following usage event) was also run
and is invalid as a visible-token calibration because (a) trace truncates recorded output
text at 512 chars and (b) per-request usage lacks reasoning_tokens; its inflated ratios
(~9x) are a symptom of exactly the Q4-H4 record truncation, not a tokenization fact.
"""
import json
import re
import statistics
from pathlib import Path

ROOT = Path("/Users/anontokyo/Downloads/Project/Learn/Trivae")
BASE = ROOT / "data/evaluation/prompt-ab-eval-v1-20261029"
OUT = ROOT / "research/agent-quality-20261029/rounds/outputs"
study = json.load(open(BASE / "study-data.json"))

MS = []
runs_out = []
for cid, case in study["cases"].items():
    for arm, rlist in case["runs"].items():
        for idx, r in enumerate(rlist):
            if r["source"] != "new-agent-run":
                continue
            au = r.get("agent_usage") or {}
            out_tok = au.get("output_tokens")
            reasoning = au.get("reasoning_tokens") or 0
            if not out_tok:
                continue
            blocks = r.get("content_blocks") or []
            texts = []
            for b in blocks:
                if isinstance(b, dict) and b.get("text"):
                    texts.append(b["text"])
                elif isinstance(b, str):
                    texts.append(b)
            answer_bytes = sum(len(t.encode("utf-8")) for t in texts)
            tp = ROOT / r["trace"]["trace_path"]
            t = json.load(open(tp))
            args_bytes = 0
            prefix = None
            for e in t["timeline"]:
                if e["operation"] != "model.output":
                    continue
                obs = e["payload"].get("observable_output") or []
                for o in obs:
                    if o.get("arguments"):
                        args_bytes += len(o["arguments"].encode("utf-8"))
                    if o.get("content"):
                        for cp in o["content"]:
                            if cp.get("text") and prefix is None:
                                prefix = cp["text"]
            M = None
            if prefix:
                m = re.search(r'"text":"((?:[^"\\]|\\.)*)"', prefix)
                if m:
                    text_raw = m.group(1)
                    end = m.end()
                    if '"limitations"' in prefix[end:] and ("]}," in prefix[end:] or "]}" in prefix[end:]):
                        close = prefix.find("]},", end)
                        if close == -1:
                            close = prefix.find("]}", end)
                        seg = prefix[: close + 3]
                        text_unesc_bytes = len(texts[0].encode("utf-8")) if texts else None
                        if text_unesc_bytes:
                            M = len(seg.encode("utf-8")) / text_unesc_bytes
            MS.append(M)
            runs_out.append({"case": cid, "arm": arm, "idx": idx, "answer_bytes": answer_bytes,
                             "args_bytes": args_bytes, "M": round(M, 3) if M else None,
                             "out_tok": out_tok, "reasoning": reasoning})

medM = statistics.median([m for m in MS if m])
print(f"claim-1 structural multiplier M: measured on {sum(1 for m in MS if m)}/{len(MS)} runs, "
      f"median={medM:.3f}, min={min(m for m in MS if m):.3f}, max={max(m for m in MS if m):.3f}")
ratios = []
for r in runs_out:
    M = r["M"] or medM
    est = (r["answer_bytes"] * M + r["args_bytes"]) / 3.0
    actual = r["out_tok"] - r["reasoning"]
    r["est"] = round(est, 1)
    r["actual_visible"] = actual
    r["ratio"] = round(actual / est, 3) if est else None
    if r["ratio"]:
        ratios.append(r["ratio"])
ratios.sort()
n = len(ratios)
summary = {
    "n_runs": n,
    "median_M_used": round(medM, 3),
    "mean_ratio": round(statistics.mean(ratios), 3),
    "median_ratio": round(statistics.median(ratios), 3),
    "p10": round(ratios[int(0.1 * n)], 3),
    "p90": round(ratios[int(0.9 * n)], 3),
    "min": round(ratios[0], 3),
    "max": round(ratios[-1], 3),
    "share_within_30pct_of_1": round(sum(1 for x in ratios if 0.7 <= x <= 1.3) / n, 3),
    "share_below_0.7": round(sum(1 for x in ratios if x < 0.7) / n, 3),
    "share_above_1.3": round(sum(1 for x in ratios if x > 1.3) / n, 3),
}
OUT.mkdir(parents=True, exist_ok=True)
json.dump({"summary": summary, "runs": runs_out}, open(OUT / "q5-token.json", "w"), ensure_ascii=False)
print(json.dumps(summary, ensure_ascii=False, indent=1))
