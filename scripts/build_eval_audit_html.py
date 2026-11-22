"""Build a self-contained offline HTML audit workstation for eval@v2 24x2 A/B experiments.

Generates a single offline HTML file inside the ignored experiment directory so reviewers
can inspect all 48 runs (24 cases x Baseline/Candidate), system answers with interactive
citation traceability, LLM Judge v3 / v2.1 scores & diagnostics, position-swapped
pairwise comparisons, and the exact System Prompt + User Context passed to the Judge.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from trivae.evaluation.capability_judge import (
    JUDGE_PROMPT_V2_1,
    JUDGE_PROMPT_V3,
    PAIRWISE_JUDGE_PROMPT,
)

DEFAULT_EXPERIMENT_DIR = Path("data/evaluation/eval-v2-e2e-20261122")
DEFAULT_OUTPUT_FILENAME = "audit-viewer.html"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_optional(path: Path) -> Any | None:
    if not path.is_file():
        return None
    return _read_json(path)


def _escape_for_script_tag(json_text: str) -> str:
    """Safely escape JSON for embedding inside <script type="application/json">."""
    return (
        json_text.replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _compute_thread_stats(threads: list[dict[str, Any]]) -> dict[str, int]:
    total = 0
    cited = 0
    reply_targets = 0
    forwarded = 0
    for thread in threads:
        for msg in thread.get("messages", []):
            total += 1
            if msg.get("is_cited"):
                cited += 1
            if msg.get("is_reply_target"):
                reply_targets += 1
            if msg.get("is_forwarded"):
                forwarded += 1
    return {
        "sessions": len(threads),
        "total_messages": total,
        "cited_messages": cited,
        "neighbor_messages": max(0, total - cited - reply_targets),
        "reply_target_messages": reply_targets,
        "forwarded_messages": forwarded,
    }


def _extract_runtime_meta(run_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run_data, dict):
        return {}
    qr = run_data.get("query_result") or {}
    rt = qr.get("runtime") or {}
    tb = rt.get("tool_behavior") or {}
    err = rt.get("error")
    return {
        "route": qr.get("route"),
        "route_source": qr.get("route_source"),
        "model": rt.get("model"),
        "provider": rt.get("provider"),
        "termination": rt.get("termination") or qr.get("termination"),
        "tool_rounds": rt.get("tool_rounds"),
        "tool_count": rt.get("tool_count"),
        "tool_sequence": tb.get("tool_sequence") or [],
        "tool_errors": tb.get("tool_errors") or [],
        "error": err,
    }


def _merge_evidence_meta(
    v3_answer: dict[str, Any] | None,
    artifact: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Keep the exact v3 answer payload, plus optional criterion/finding lookup from answer_artifact."""
    if v3_answer is None and artifact is None:
        return None
    base = dict(v3_answer or {})
    if artifact is not None:
        if "content_blocks" not in base:
            base["content_blocks"] = artifact.get("content_blocks", [])
        if "citation_bindings" not in base:
            base["citation_bindings"] = artifact.get("citation_bindings", [])
        if "limitations" not in base:
            base["limitations"] = artifact.get("limitations", [])
        item_meta: dict[str, dict[str, Any]] = {}
        for item in artifact.get("evidence_items", []):
            eid = item.get("evidence_id")
            if isinstance(eid, str):
                item_meta[eid] = {
                    "criterion": item.get("criterion"),
                    "finding": item.get("finding"),
                    "source_count": len(item.get("sources") or []),
                }
        base["_artifact_evidence_meta"] = item_meta
    return base


def _load_arm_record(
    experiment_dir: Path,
    arm: str,
    case_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Load one arm's run, answer, judge-v3, and judge-v2.1 records.

    Returns (arm_payload, shared_case_context_if_available).
    """
    case_dir = experiment_dir / arm / "cases" / case_id
    summary = _read_json(case_dir / "summary.json")
    run_data = _read_json_optional(case_dir / "run.json")
    artifact = _read_json_optional(case_dir / "answer_artifact.json")

    v3_dir = experiment_dir / "judge-v3" / arm / case_id
    v3_input_path = v3_dir / "input.json"
    v3_input = _read_json_optional(v3_input_path)
    v3_review = _read_json_optional(v3_dir / "review.json")
    v3_response = _read_json_optional(v3_dir / "response.json")

    v2_dir = experiment_dir / "judge" / arm / case_id
    v2_input_path = v2_dir / "input.json"
    v2_input = _read_json_optional(v2_input_path)
    v2_review = _read_json_optional(v2_dir / "review.json")
    v2_response = _read_json_optional(v2_dir / "response.json")

    shared_ctx: dict[str, Any] | None = None
    if isinstance(v3_input, dict):
        shared_ctx = {
            "case_id": v3_input.get("case_id", case_id),
            "case_version": v3_input.get("case_version"),
            "as_of": v3_input.get("as_of"),
            "query": v3_input.get("query"),
            "ground_truth": v3_input.get("ground_truth"),
            "reference_evidence": v3_input.get("reference_evidence", []),
        }

    judge_v3_block: dict[str, Any] | None = None
    if v3_review is not None:
        threads = (v3_input or {}).get("evidence_threads", [])
        judge_v3_block = {
            "review": v3_review,
            "model": (v3_response or {}).get("model"),
            "provider": (v3_response or {}).get("provider"),
            "latency_ms": (v3_response or {}).get("latency_ms"),
            "usage": (v3_response or {}).get("usage"),
            "input_chars": v3_input_path.stat().st_size if v3_input_path.is_file() else 0,
            "limitations": (v3_input or {}).get("limitations"),
            "thread_stats": _compute_thread_stats(threads),
            "evidence_threads": threads,
        }

    judge_v2_block: dict[str, Any] | None = None
    if v2_review is not None:
        judge_v2_block = {
            "review": v2_review,
            "model": (v2_response or {}).get("model"),
            "provider": (v2_response or {}).get("provider"),
            "latency_ms": (v2_response or {}).get("latency_ms"),
            "usage": (v2_response or {}).get("usage"),
            "input_chars": v2_input_path.stat().st_size if v2_input_path.is_file() else 0,
            "cited_messages_count": len((v2_input or {}).get("cited_messages", [])),
        }

    answer_payload = _merge_evidence_meta(
        (v3_input or {}).get("answer") if isinstance(v3_input, dict) else None,
        artifact,
    )

    arm_record: dict[str, Any] = {
        "arm": arm,
        "summary": summary,
        "runtime": _extract_runtime_meta(run_data),
        "answer": answer_payload,
        "judge_v3": judge_v3_block,
        "judge_v2_1": judge_v2_block,
    }
    return arm_record, shared_ctx


def _load_pairwise_record(experiment_dir: Path, case_id: str) -> dict[str, Any] | None:
    pw_dir = experiment_dir / "pairwise-v1" / case_id
    agg = _read_json_optional(pw_dir / "aggregated.json")
    if agg is None:
        return None
    fwd = _read_json_optional(pw_dir / "forward-ab.json")
    rev = _read_json_optional(pw_dir / "reverse-ba.json")
    fwd_resp = _read_json_optional(pw_dir / "response-forward-ab.json")
    rev_resp = _read_json_optional(pw_dir / "response-reverse-ba.json")
    fwd_in = pw_dir / "input-forward-ab.json"
    return {
        "aggregated": agg,
        "forward_ab": fwd,
        "reverse_ba": rev,
        "forward_usage": (fwd_resp or {}).get("usage"),
        "reverse_usage": (rev_resp or {}).get("usage"),
        "forward_latency_ms": (fwd_resp or {}).get("latency_ms"),
        "reverse_latency_ms": (rev_resp or {}).get("latency_ms"),
        "input_chars": fwd_in.stat().st_size if fwd_in.is_file() else 0,
    }


def collect_audit_dataset(experiment_dir: Path) -> dict[str, Any]:
    baseline_cases_dir = experiment_dir / "baseline" / "cases"
    case_ids = sorted(p.name for p in baseline_cases_dir.iterdir() if p.is_dir())

    baseline_manifest = _read_json_optional(experiment_dir / "baseline" / "manifest.json") or {}
    candidate_manifest = _read_json_optional(experiment_dir / "candidate" / "manifest.json") or {}
    summary_v3 = _read_json_optional(experiment_dir / "report-v3" / "ab-summary.json") or {}
    summary_v2 = _read_json_optional(experiment_dir / "report" / "ab-summary.json") or {}

    cases: list[dict[str, Any]] = []
    for case_id in case_ids:
        b_arm, b_ctx = _load_arm_record(experiment_dir, "baseline", case_id)
        c_arm, c_ctx = _load_arm_record(experiment_dir, "candidate", case_id)
        shared = c_ctx or b_ctx
        if shared is None:
            raise ValueError(f"Case {case_id} has neither baseline nor candidate judge-v3 input")
        pairwise = _load_pairwise_record(experiment_dir, case_id)
        gt = shared.get("ground_truth") or {}
        cases.append(
            {
                "case_id": case_id,
                "case_version": shared.get("case_version"),
                "category": gt.get("category", "未分类"),
                "query": shared.get("query") or gt.get("query") or "",
                "as_of": shared.get("as_of") or {},
                "ground_truth": gt,
                "reference_evidence": shared.get("reference_evidence", []),
                "arms": {
                    "baseline": b_arm,
                    "candidate": c_arm,
                },
                "pairwise": pairwise,
            }
        )

    def _safe_variant_summary(manifest: dict[str, Any]) -> dict[str, Any]:
        var = manifest.get("variant") or {}
        return {
            "arm": manifest.get("arm"),
            "variant_id": var.get("variant_id"),
            "provider": var.get("provider"),
            "model": var.get("model"),
            "prompt_identity": var.get("prompt_identity"),
            "retrieval_configuration": var.get("retrieval_configuration"),
            "budget": var.get("budget"),
            "available_tools": var.get("available_tools"),
            "commit": manifest.get("commit"),
            "freeze_id": manifest.get("freeze_id"),
        }

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "experiment_dir": str(experiment_dir),
        "suite": summary_v3.get("suite") or "eval@v2",
        "variants": {
            "baseline": _safe_variant_summary(baseline_manifest),
            "candidate": _safe_variant_summary(candidate_manifest),
        },
        "ab_summary_v3": summary_v3,
        "ab_summary_v2_1": summary_v2,
        "prompts": {
            "eval-rubric-v3": JUDGE_PROMPT_V3.strip(),
            "eval-rubric-v2.1": JUDGE_PROMPT_V2_1.strip(),
            "eval-pairwise-v1": PAIRWISE_JUDGE_PROMPT.strip(),
        },
        "cases": cases,
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Trivae eval@v2 (24×2 = 48 次实验) · 人工审核与 LLM Judge 透视台</title>
<style>
:root {
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-subtle: #f9fafb;
  --surface-tint: #f1f5f9;
  --border: #e2e8f0;
  --border-strong: #cbd5e1;
  --text: #0f172a;
  --text-secondary: #475569;
  --text-muted: #64748b;
  --accent: #2563eb;
  --accent-soft: #eff6ff;
  --accent-border: #bfdbfe;
  --green: #059669;
  --green-soft: #ecfdf5;
  --green-border: #a7f3d0;
  --blue: #2563eb;
  --blue-soft: #eff6ff;
  --blue-border: #bfdbfe;
  --amber: #d97706;
  --amber-soft: #fffbeb;
  --amber-border: #fde68a;
  --red: #dc2626;
  --red-soft: #fef2f2;
  --red-border: #fecaca;
  --purple: #7c3aed;
  --purple-soft: #f5f3ff;
  --purple-border: #ddd6fe;
  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 4px 12px rgba(15, 23, 42, 0.08);
  --radius: 10px;
  --radius-sm: 6px;
  --font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; height: 100%; background: var(--bg); color: var(--text); font-family: var(--font-sans); font-size: 14px; line-height: 1.6; }

/* Top Header */
.topbar {
  position: sticky; top: 0; z-index: 40;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  padding: 10px 18px;
  display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
.brand { display: flex; align-items: center; gap: 10px; }
.brand-logo {
  width: 30px; height: 30px; border-radius: 8px;
  background: linear-gradient(135deg, #1d4ed8, #4f46e5);
  color: #fff; font-weight: 700; font-size: 15px;
  display: flex; align-items: center; justify-content: center;
}
.brand-title { font-size: 15px; font-weight: 700; letter-spacing: -0.01em; }
.brand-sub { font-size: 12px; color: var(--text-muted); }

.topbar-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 11px; border-radius: var(--radius-sm);
  border: 1px solid var(--border-strong); background: var(--surface);
  color: var(--text); font-size: 12.5px; font-weight: 500; cursor: pointer;
  transition: all 0.14s ease;
}
.btn:hover { background: var(--surface-tint); border-color: #94a3b8; }
.btn-primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn-primary:hover { background: #1d4ed8; border-color: #1d4ed8; }
.btn-sm { padding: 4px 8px; font-size: 12px; }
.btn-ghost { border-color: transparent; background: transparent; color: var(--text-secondary); }
.btn-ghost:hover { background: var(--surface-tint); color: var(--text); }

/* Main App Layout */
.app-shell {
  display: grid;
  grid-template-columns: 320px 1fr;
  height: calc(100vh - 55px);
  overflow: hidden;
}

/* Sidebar */
.sidebar {
  background: var(--surface);
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column;
  height: 100%; overflow: hidden;
}
.sidebar-controls {
  padding: 12px;
  border-bottom: 1px solid var(--border);
  display: flex; flex-direction: column; gap: 8px;
}
.search-input {
  width: 100%; padding: 7px 10px;
  border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
  font-size: 13px; outline: none; background: var(--surface-subtle);
}
.search-input:focus { border-color: var(--accent); background: #fff; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1); }
.filter-pills { display: flex; flex-wrap: wrap; gap: 5px; }
.pill {
  padding: 3px 8px; border-radius: 999px; font-size: 11.5px; font-weight: 500;
  border: 1px solid var(--border); background: var(--surface-subtle); color: var(--text-secondary);
  cursor: pointer; user-select: none;
}
.pill:hover { border-color: #94a3b8; }
.pill.active { background: var(--accent); border-color: var(--accent); color: #fff; }

.case-list { flex: 1; overflow-y: auto; padding: 6px; }
.case-item {
  padding: 10px 10px; border-radius: 8px; cursor: pointer;
  border: 1px solid transparent; margin-bottom: 4px;
  transition: background 0.12s, border-color 0.12s;
}
.case-item:hover { background: var(--surface-subtle); border-color: var(--border); }
.case-item.active { background: var(--accent-soft); border-color: var(--accent-border); }
.case-item-top { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-bottom: 4px; }
.case-id { font-family: var(--font-mono); font-size: 11.5px; font-weight: 600; color: var(--text); }
.case-cat { font-size: 11px; color: var(--text-muted); background: var(--surface-tint); padding: 1px 6px; border-radius: 4px; }
.case-query {
  font-size: 12.5px; color: var(--text-secondary);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  line-height: 1.45; margin-bottom: 6px;
}
.case-scores-row { display: flex; align-items: center; justify-content: space-between; gap: 4px; font-size: 11px; font-family: var(--font-mono); }
.mini-arm { display: inline-flex; align-items: center; gap: 3px; }
.mini-tag { font-weight: 700; color: var(--text-muted); font-size: 10.5px; }

/* Score badges */
.sc {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 19px; height: 19px; padding: 0 5px;
  border-radius: 4px; font-family: var(--font-mono); font-size: 11px; font-weight: 700;
}
.sc-4 { background: var(--green-soft); color: var(--green); border: 1px solid var(--green-border); }
.sc-3 { background: var(--blue-soft); color: var(--blue); border: 1px solid var(--blue-border); }
.sc-2 { background: var(--amber-soft); color: var(--amber); border: 1px solid var(--amber-border); }
.sc-1, .sc-0 { background: var(--red-soft); color: var(--red); border: 1px solid var(--red-border); }
.sc-unknown { background: var(--purple-soft); color: var(--purple); border: 1px solid var(--purple-border); }
.sc-fail { background: var(--red-soft); color: var(--red); border: 1px solid var(--red-border); }

.badge {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 2px 7px; border-radius: 999px; font-size: 11px; font-weight: 600;
  border: 1px solid var(--border); background: var(--surface-tint); color: var(--text-secondary);
}
.badge-high { background: var(--red-soft); color: var(--red); border-color: var(--red-border); }
.badge-medium { background: var(--amber-soft); color: var(--amber); border-color: var(--amber-border); }
.badge-low { background: var(--blue-soft); color: var(--blue); border-color: var(--blue-border); }
.badge-none { background: var(--green-soft); color: var(--green); border-color: var(--green-border); }
.badge-purple { background: var(--purple-soft); color: var(--purple); border-color: var(--purple-border); }
.badge-cwin { background: var(--green-soft); color: var(--green); border-color: var(--green-border); }
.badge-bwin { background: var(--blue-soft); color: var(--blue); border-color: var(--blue-border); }
.badge-tie { background: var(--surface-tint); color: var(--text-muted); border-color: var(--border); }
.badge-inconsistent { background: var(--amber-soft); color: var(--amber); border-color: var(--amber-border); }
.badge-audited { background: #ecfeff; color: #0e7490; border-color: #a5f3fc; }

/* Main Content Area */
.main {
  overflow-y: auto;
  padding: 18px 22px 60px;
  display: flex; flex-direction: column; gap: 14px;
}

/* KPI Strip */
.kpi-strip {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px;
}
.kpi-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px 14px; box-shadow: var(--shadow-sm);
}
.kpi-label { font-size: 11.5px; color: var(--text-muted); font-weight: 600; margin-bottom: 4px; }
.kpi-val { font-size: 17px; font-weight: 700; color: var(--text); letter-spacing: -0.01em; }
.kpi-sub { font-size: 11.5px; color: var(--text-secondary); margin-top: 3px; }

/* Card & Case Header */
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow-sm); overflow: hidden;
}
.card-header {
  padding: 14px 16px; border-bottom: 1px solid var(--border);
  background: var(--surface-subtle);
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap;
}
.card-body { padding: 16px; }

.question-title { font-size: 18px; font-weight: 700; color: var(--text); margin: 4px 0 8px; line-height: 1.45; }
.meta-grid { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 12.5px; color: var(--text-secondary); }
.meta-item strong { color: var(--text); font-weight: 600; }

/* View Tabs */
.tabs {
  display: flex; align-items: center; gap: 4px; flex-wrap: wrap;
  background: var(--surface-tint); padding: 4px; border-radius: 8px; border: 1px solid var(--border);
}
.tab-btn {
  padding: 6px 12px; border: none; background: transparent; border-radius: 6px;
  font-size: 12.5px; font-weight: 600; color: var(--text-secondary); cursor: pointer;
}
.tab-btn:hover { color: var(--text); background: rgba(255,255,255,0.6); }
.tab-btn.active { background: var(--surface); color: var(--accent); box-shadow: var(--shadow-sm); }

/* Split A/B Columns */
.ab-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
.ab-grid.single-col { grid-template-columns: 1fr; }
@media (max-width: 1280px) {
  .ab-grid { grid-template-columns: 1fr; }
}

/* Arm Panel */
.arm-panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
  box-shadow: var(--shadow-sm); overflow: hidden;
}
.arm-header {
  padding: 12px 15px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
}
.arm-header.baseline { background: linear-gradient(90deg, #f8fafc, #f1f5f9); border-top: 3px solid #64748b; }
.arm-header.candidate { background: linear-gradient(90deg, #eff6ff, #f0fdf4); border-top: 3px solid #2563eb; }
.arm-title { font-size: 14.5px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
.telemetry-bar {
  padding: 8px 15px; background: var(--surface-subtle); border-bottom: 1px solid var(--border);
  display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 11.5px; color: var(--text-secondary);
  font-family: var(--font-mono);
}

/* Section inside Arm Panel */
.arm-section { padding: 14px 15px; border-bottom: 1px solid var(--border); }
.arm-section:last-child { border-bottom: none; }
.section-heading {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap;
  margin-bottom: 10px;
}
.section-title { font-size: 13px; font-weight: 700; color: var(--text); text-transform: uppercase; letter-spacing: 0.02em; display: flex; align-items: center; gap: 6px; }

/* Answer Blocks */
.answer-block {
  padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border);
  background: #fff; margin-bottom: 8px; transition: box-shadow 0.2s, border-color 0.2s;
}
.answer-block.highlight-pulse {
  border-color: var(--amber); background: var(--amber-soft);
  box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.2);
}
.block-meta { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-bottom: 5px; flex-wrap: wrap; }
.block-id { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); font-weight: 600; }
.block-text { font-size: 13.8px; line-height: 1.72; color: var(--text); white-space: pre-wrap; word-break: break-word; }
.cite-chips { display: inline-flex; flex-wrap: wrap; gap: 4px; }
.cite-chip {
  font-family: var(--font-mono); font-size: 11px; font-weight: 600;
  padding: 1px 6px; border-radius: 4px; cursor: pointer;
  background: var(--accent-soft); color: var(--accent); border: 1px solid var(--accent-border);
}
.cite-chip:hover, .cite-chip.open { background: var(--accent); color: #fff; }
.cite-drawer {
  margin-top: 8px; padding: 10px 12px; border-radius: 6px;
  background: var(--surface-subtle); border: 1px dashed var(--accent-border);
  font-size: 12.5px;
}
.limitations-box {
  margin-top: 10px; padding: 10px 12px; border-radius: 8px;
  background: #fafafa; border: 1px solid var(--border); font-size: 12.5px; color: var(--text-secondary);
}
.limitations-box ul { margin: 4px 0 0 18px; padding: 0; }

/* Failed run box */
.failed-box {
  padding: 14px; border-radius: 8px; background: var(--red-soft); border: 1px solid var(--red-border);
  color: #991b1b;
}
.failed-box pre {
  margin: 8px 0 0; padding: 8px; background: rgba(255,255,255,0.8); border-radius: 6px;
  font-family: var(--font-mono); font-size: 11.5px; overflow-x: auto; white-space: pre-wrap;
}

/* Judge Axes & Diagnostics */
.axes-grid { display: grid; grid-template-columns: 1fr; gap: 8px; margin-bottom: 10px; }
.axis-card {
  padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-subtle);
}
.axis-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 5px; }
.axis-name { font-weight: 700; font-size: 13px; color: var(--text); }
.axis-score-big {
  font-family: var(--font-mono); font-size: 13px; font-weight: 800;
  padding: 2px 9px; border-radius: 6px;
}
.axis-reason { font-size: 13px; color: var(--text-secondary); line-height: 1.65; }

.judge-notes {
  padding: 10px 12px; border-radius: 8px; background: #f8fafc; border-left: 3px solid var(--accent);
  font-size: 12.8px; color: var(--text-secondary); margin-bottom: 10px; line-height: 1.65;
}

.diag-card {
  padding: 10px 12px; border-radius: 8px; border: 1px solid var(--border);
  background: #fff; margin-bottom: 8px; font-size: 12.6px;
}
.diag-card.sev-severe { border-left: 4px solid var(--red); }
.diag-card.sev-moderate { border-left: 4px solid var(--amber); }
.diag-card.sev-minor { border-left: 4px solid #94a3b8; }
.diag-header { display: flex; align-items: center; justify-content: space-between; gap: 6px; flex-wrap: wrap; margin-bottom: 6px; }
.diag-field { margin-top: 5px; line-height: 1.6; }
.diag-field-label { font-weight: 700; color: var(--text); margin-right: 4px; }
.diag-excerpt {
  display: inline-block; background: var(--amber-soft); border: 1px solid var(--amber-border);
  padding: 2px 7px; border-radius: 4px; color: #92400e; font-size: 12.2px;
}

/* Evidence Threads (Chat Log Viewer) */
.context-stats {
  display: flex; flex-wrap: wrap; gap: 6px 12px; font-size: 12px; color: var(--text-secondary);
  background: var(--surface-subtle); padding: 8px 10px; border-radius: 6px; border: 1px solid var(--border);
  margin-bottom: 10px;
}
.thread-box {
  border: 1px solid var(--border); border-radius: 8px; margin-bottom: 10px; overflow: hidden;
}
.thread-header {
  padding: 8px 12px; background: var(--surface-tint); border-bottom: 1px solid var(--border);
  font-size: 12.5px; font-weight: 700; display: flex; align-items: center; justify-content: space-between;
  cursor: pointer;
}
.thread-messages { max-height: 460px; overflow-y: auto; padding: 8px 10px; background: #fff; }
.msg-row {
  padding: 7px 9px; border-radius: 6px; margin-bottom: 5px; font-size: 12.5px;
  border: 1px solid transparent; background: #f8fafc;
}
.msg-row.is-cited { background: #eff6ff; border-color: #93c5fd; }
.msg-row.is-reply-target { background: #f5f3ff; border-color: #c4b5fd; }
.msg-head {
  display: flex; align-items: center; justify-content: space-between; gap: 6px; flex-wrap: wrap;
  font-size: 11.5px; color: var(--text-muted); margin-bottom: 3px;
}
.msg-sender { font-weight: 700; color: var(--text); }
.msg-time { font-family: var(--font-mono); font-size: 11px; }
.msg-id { font-family: var(--font-mono); font-size: 10.5px; color: #94a3b8; }
.msg-body { white-space: pre-wrap; word-break: break-word; color: var(--text); line-height: 1.55; }

/* Code / Raw JSON block */
.code-pre {
  background: #0f172a; color: #e2e8f0; padding: 12px 14px; border-radius: 8px;
  font-family: var(--font-mono); font-size: 11.8px; line-height: 1.55;
  overflow-x: auto; max-height: 520px; overflow-y: auto; white-space: pre-wrap; word-break: break-word;
}

/* Human Audit Panel */
.human-audit-box {
  background: linear-gradient(180deg, #f0f9ff 0%, #ffffff 100%);
  border: 1px solid #bae6fd; border-radius: 8px; padding: 12px;
}
.verdict-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; }
.verdict-btn {
  padding: 5px 10px; border-radius: 6px; border: 1px solid var(--border-strong);
  background: #fff; font-size: 12px; font-weight: 600; cursor: pointer;
}
.verdict-btn.active-agree { background: var(--green); border-color: var(--green); color: #fff; }
.verdict-btn.active-partial { background: var(--amber); border-color: var(--amber); color: #fff; }
.verdict-btn.active-disagree { background: var(--red); border-color: var(--red); color: #fff; }
.human-scores { display: flex; flex-wrap: wrap; gap: 10px; margin: 8px 0; align-items: center; font-size: 12px; }
.human-scores select {
  padding: 3px 6px; border-radius: 4px; border: 1px solid var(--border-strong); font-family: var(--font-mono); font-size: 12px;
}
.human-note {
  width: 100%; min-height: 56px; padding: 8px 10px; border-radius: 6px;
  border: 1px solid var(--border-strong); font-family: var(--font-sans); font-size: 12.5px; resize: vertical;
}

/* Summary Matrix Table */
.matrix-wrap { overflow-x: auto; }
table.matrix { width: 100%; border-collapse: collapse; font-size: 12.2px; }
table.matrix th, table.matrix td {
  padding: 7px 9px; border-bottom: 1px solid var(--border); text-align: left; white-space: nowrap;
}
table.matrix th { background: var(--surface-subtle); font-weight: 700; color: var(--text-secondary); position: sticky; top: 0; }
table.matrix tr:hover td { background: var(--accent-soft); cursor: pointer; }
table.matrix td.q-col { white-space: normal; min-width: 240px; max-width: 360px; }

/* Modal */
.modal-backdrop {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.55); z-index: 100;
  display: none; align-items: center; justify-content: center; padding: 20px;
}
.modal-backdrop.open { display: flex; }
.modal {
  background: var(--surface); border-radius: 12px; max-width: 980px; width: 100%;
  max-height: 88vh; display: flex; flex-direction: column; box-shadow: 0 20px 50px rgba(0,0,0,0.25);
  overflow: hidden;
}
.modal-head {
  padding: 14px 18px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.modal-body { padding: 16px 18px; overflow-y: auto; flex: 1; }

.sub-tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.sub-tab {
  padding: 4px 10px; border-radius: 6px; border: 1px solid var(--border);
  background: var(--surface-subtle); font-size: 12px; font-weight: 600; color: var(--text-secondary); cursor: pointer;
}
.sub-tab.active { background: var(--accent); border-color: var(--accent); color: #fff; }

.muted { color: var(--text-muted); }
.mono { font-family: var(--font-mono); }
.flex-between { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.mt-8 { margin-top: 8px; }
.mb-8 { margin-bottom: 8px; }
</style>
</head>
<body>

<header class="topbar">
  <div class="brand">
    <div class="brand-logo">T</div>
    <div>
      <div class="brand-title">Trivae eval@v2 人工审核与 LLM Judge 透视台</div>
      <div class="brand-sub" id="header-sub">24 题 × 2 组 = 48 次实验 · 45 份完整评分 · 21 组换位盲比</div>
    </div>
  </div>
  <div class="topbar-actions">
    <span class="badge badge-audited" id="audit-progress-badge">我已审核: 0 / 48</span>
    <button class="btn" id="btn-toggle-matrix">📊 全量 48 次总览表</button>
    <button class="btn btn-primary" id="btn-open-prompt-modal">📋 LLM Judge 上下文与 Prompt 架构</button>
    <button class="btn" id="btn-export-audit">💾 导出我的审核 (JSON)</button>
    <label class="btn" style="margin:0;">📂 导入审核<input type="file" id="input-import-audit" accept=".json" style="display:none;" /></label>
  </div>
</header>

<div class="app-shell">
  <aside class="sidebar">
    <div class="sidebar-controls">
      <input type="text" id="search-box" class="search-input" placeholder="搜索题号、问题、分类、诊断关键词..." />
      <div class="filter-pills" id="filter-pills">
        <span class="pill active" data-filter="all">全部 (24)</span>
        <span class="pill" data-filter="adjudicate">需审定</span>
        <span class="pill" data-filter="high">高优/unknown</span>
        <span class="pill" data-filter="failed">含失败 (3)</span>
        <span class="pill" data-filter="diff">A/B分差</span>
        <span class="pill" data-filter="inconsistent">盲比不一致</span>
        <span class="pill" data-filter="unaudited">未审核</span>
        <span class="pill" data-filter="audited">已审核</span>
      </div>
    </div>
    <div class="case-list" id="case-list"></div>
  </aside>

  <main class="main" id="main-area">
    <div id="kpi-container"></div>
    <div id="matrix-container" style="display:none;"></div>
    <div id="case-detail-container"></div>
  </main>
</div>

<!-- Prompt & Context Architecture Modal -->
<div class="modal-backdrop" id="prompt-modal">
  <div class="modal">
    <div class="modal-head">
      <div style="font-size:15px;font-weight:700;">📋 传给 LLM Judge 的完整 System Prompt 与上下文结构</div>
      <button class="btn btn-sm" id="btn-close-prompt-modal">✕ 关闭</button>
    </div>
    <div class="modal-body" id="prompt-modal-body"></div>
  </div>
</div>

<script type="application/json" id="audit-data">__AUDIT_DATA_JSON__</script>

<script>
(function() {
  const DATA = JSON.parse(document.getElementById('audit-data').textContent);
  const STORAGE_KEY = 'trivae_eval_v2_human_audit_v1';

  const state = {
    selectedCaseId: DATA.cases[0]?.case_id || null,
    filter: 'all',
    search: '',
    viewMode: 'ab', // 'ab' | 'baseline' | 'candidate' | 'pairwise' | 'gt'
    rubricTab: { baseline: 'v3', candidate: 'v3' },
    contextTab: { baseline: 'threads', candidate: 'threads' }, // 'threads' | 'answer_struct' | 'raw'
    threadOnlyCited: { baseline: false, candidate: false },
    threadSearch: { baseline: '', candidate: '' },
    showMatrix: false,
    humanAudit: loadHumanAudit(),
  };

  function loadHumanAudit() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') || {};
    } catch { return {}; }
  }
  function saveHumanAudit() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state.humanAudit));
    } catch (e) { console.warn('localStorage save failed', e); }
    updateAuditProgressBadge();
  }
  function auditKey(caseId, arm) { return `${caseId}::${arm}`; }
  function getAudit(caseId, arm) { return state.humanAudit[auditKey(caseId, arm)] || null; }

  function esc(val) {
    if (val === null || val === undefined) return '';
    return String(val)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtNum(n) {
    if (n === null || n === undefined) return '-';
    return Number(n).toLocaleString('en-US');
  }

  function fmtMsToIso(ms) {
    if (typeof ms !== 'number') return '';
    const d = new Date(ms + 8 * 3600 * 1000);
    return d.toISOString().replace('T', ' ').slice(0, 19) + ' +08';
  }

  function scoreClass(score) {
    if (score === 'unknown') return 'sc-unknown';
    if (score === null || score === undefined) return 'sc-fail';
    const n = Number(score);
    if (n >= 4) return 'sc-4';
    if (n === 3) return 'sc-3';
    if (n === 2) return 'sc-2';
    return 'sc-1';
  }

  function scoreLabel(score) {
    if (score === 'unknown') return 'UNK';
    if (score === null || score === undefined) return 'FAIL';
    return String(score);
  }

  const AXIS_CN = {
    task_satisfaction: '任务满足度 (task_satisfaction)',
    evidence_grounding: '事实与引用忠实度 (evidence_grounding)',
    epistemic_calibration: '边界与克制度 (epistemic_calibration)',
    answer_reliability: '回答可信度 (answer_reliability)',
  };

  const DIAG_CN = {
    unsupported_assertion: '无依据/过度断言',
    factual_error: '事实错误',
    attribution_error: '发言人/来源归属错误',
    citation_mismatch: '引用与原文错配',
    temporal_or_scope_error: '时效/适用范围越界',
    omitted_key_information: '遗漏关键信息',
    other: '其他问题',
  };

  function getV3Scores(armObj) {
    const qa = armObj?.judge_v3?.review?.quality_axes;
    if (!qa) return null;
    return {
      t: qa.task_satisfaction?.score,
      g: qa.evidence_grounding?.score,
      c: qa.epistemic_calibration?.score,
    };
  }

  function getPriority(armObj) {
    return armObj?.judge_v3?.review?.adjudication_priority || null;
  }

  function caseHasAdjudication(c) {
    return Boolean(
      c.arms.baseline?.judge_v3?.review?.needs_adjudication ||
      c.arms.candidate?.judge_v3?.review?.needs_adjudication
    );
  }

  function caseIsHigh(c) {
    return getPriority(c.arms.baseline) === 'high' || getPriority(c.arms.candidate) === 'high';
  }

  function caseHasFailed(c) {
    return c.arms.baseline?.summary?.terminal_status !== 'completed' ||
           c.arms.candidate?.summary?.terminal_status !== 'completed';
  }

  function caseHasDiff(c) {
    const b = getV3Scores(c.arms.baseline);
    const k = getV3Scores(c.arms.candidate);
    if (!b || !k) return true;
    return b.t !== k.t || b.g !== k.g || b.c !== k.c;
  }

  function caseIsInconsistent(c) {
    return c.pairwise && c.pairwise.aggregated && c.pairwise.aggregated.overall_consistent === false;
  }

  function caseIsAudited(c) {
    const a1 = getAudit(c.case_id, 'baseline');
    const a2 = getAudit(c.case_id, 'candidate');
    return Boolean((a1 && (a1.verdict || a1.note)) || (a2 && (a2.verdict || a2.note)));
  }

  function updateAuditProgressBadge() {
    let count = 0;
    for (const c of DATA.cases) {
      for (const arm of ['baseline', 'candidate']) {
        const a = getAudit(c.case_id, arm);
        if (a && (a.verdict || (a.note && a.note.trim()))) count++;
      }
    }
    document.getElementById('audit-progress-badge').textContent = `我已审核: ${count} / ${DATA.cases.length * 2}`;
  }

  function filteredCases() {
    const q = state.search.trim().toLowerCase();
    return DATA.cases.filter(c => {
      if (state.filter === 'adjudicate' && !caseHasAdjudication(c)) return false;
      if (state.filter === 'high' && !caseIsHigh(c)) return false;
      if (state.filter === 'failed' && !caseHasFailed(c)) return false;
      if (state.filter === 'diff' && !caseHasDiff(c)) return false;
      if (state.filter === 'inconsistent' && !caseIsInconsistent(c)) return false;
      if (state.filter === 'audited' && !caseIsAudited(c)) return false;
      if (state.filter === 'unaudited' && caseIsAudited(c)) return false;
      if (q) {
        const hay = [
          c.case_id, c.category, c.query,
          c.ground_truth?.user_need || '',
          JSON.stringify(c.arms.baseline?.judge_v3?.review?.diagnostics || []),
          JSON.stringify(c.arms.candidate?.judge_v3?.review?.diagnostics || []),
        ].join(' ').toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function pairwiseBadgeHtml(pw) {
    if (!pw || !pw.aggregated) return '<span class="badge badge-tie">无盲比</span>';
    const w = pw.aggregated.overall_winner;
    if (w === 'candidate') return '<span class="badge badge-cwin">盲比: C胜</span>';
    if (w === 'baseline') return '<span class="badge badge-bwin">盲比: B胜</span>';
    if (w === 'tie_position_inconsistent') return '<span class="badge badge-inconsistent">盲比: 换位不一致</span>';
    return '<span class="badge badge-tie">盲比: 平局</span>';
  }

  function renderSidebar() {
    const list = filteredCases();
    const el = document.getElementById('case-list');
    if (!list.length) {
      el.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px;">没有匹配的题目</div>';
      return;
    }
    el.innerHTML = list.map(c => {
      const b = getV3Scores(c.arms.baseline);
      const k = getV3Scores(c.arms.candidate);
      const bHtml = b
        ? `<span class="sc ${scoreClass(b.t)}">${scoreLabel(b.t)}</span><span class="sc ${scoreClass(b.g)}">${scoreLabel(b.g)}</span><span class="sc ${scoreClass(b.c)}">${scoreLabel(b.c)}</span>`
        : `<span class="sc sc-fail">FAIL</span>`;
      const cHtml = k
        ? `<span class="sc ${scoreClass(k.t)}">${scoreLabel(k.t)}</span><span class="sc ${scoreClass(k.g)}">${scoreLabel(k.g)}</span><span class="sc ${scoreClass(k.c)}">${scoreLabel(k.c)}</span>`
        : `<span class="sc sc-fail">FAIL</span>`;
      const highDot = caseIsHigh(c) ? '<span class="badge badge-high" style="padding:0 5px;font-size:10px;">HIGH</span>' : '';
      const audDot = caseIsAudited(c) ? '<span class="badge badge-audited" style="padding:0 5px;font-size:10px;">✓已审</span>' : '';
      return `
        <div class="case-item ${c.case_id === state.selectedCaseId ? 'active' : ''}" data-cid="${esc(c.case_id)}">
          <div class="case-item-top">
            <span class="case-id">${esc(c.case_id)}</span>
            <span style="display:flex;gap:4px;align-items:center;">${highDot}${audDot}<span class="case-cat">${esc(c.category)}</span></span>
          </div>
          <div class="case-query">${esc(c.query)}</div>
          <div class="case-scores-row">
            <span class="mini-arm"><span class="mini-tag">B:</span>${bHtml}</span>
            <span class="mini-arm"><span class="mini-tag">C:</span>${cHtml}</span>
            ${pairwiseBadgeHtml(c.pairwise)}
          </div>
        </div>
      `;
    }).join('');

    el.querySelectorAll('.case-item').forEach(node => {
      node.addEventListener('click', () => {
        state.selectedCaseId = node.dataset.cid;
        renderSidebar();
        renderCaseDetail();
      });
    });
  }

  function renderKpis() {
    const s3 = DATA.ab_summary_v3 || {};
    const b = s3.baseline || {};
    const c = s3.candidate || {};
    const paired = s3.paired_completed_both || {};
    const pAxes = paired.axes || {};
    const pwWins = { candidate: 0, baseline: 0, tie: 0, inc: 0 };
    for (const cs of DATA.cases) {
      const w = cs.pairwise?.aggregated?.overall_winner;
      if (w === 'candidate') pwWins.candidate++;
      else if (w === 'baseline') pwWins.baseline++;
      else if (w === 'tie_position_inconsistent') pwWins.inc++;
      else if (w === 'tie') pwWins.tie++;
    }
    const totalJudged = (b.judged || 0) + (c.judged || 0);
    const totalAdj = (b.needs_adjudication || 0) + (c.needs_adjudication || 0);

    document.getElementById('kpi-container').innerHTML = `
      <div class="kpi-strip">
        <div class="kpi-card">
          <div class="kpi-label">实验规模与交付率 (24 题 × 2 组)</div>
          <div class="kpi-val">48 次运行 · 45 份已评</div>
          <div class="kpi-sub">Baseline <strong>${b.completed || 0}/24</strong> (${((b.delivery_rate||0)*100).toFixed(1)}%) → Candidate <strong>${c.completed || 0}/24</strong> (${((c.delivery_rate||0)*100).toFixed(1)}%) · 引号修复 ${c.quote_repaired_runs||0} 题 (${c.quote_repaired_total_quotes||0} 处)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Judge v3 配对均分 (n=${paired.count || 0})</div>
          <div class="kpi-val">T ${pAxes.task_satisfaction?.baseline_mean?.toFixed(2)}→${pAxes.task_satisfaction?.candidate_mean?.toFixed(2)} · G ${pAxes.evidence_grounding?.baseline_mean?.toFixed(2)}→${pAxes.evidence_grounding?.candidate_mean?.toFixed(2)}</div>
          <div class="kpi-sub">克制度 (Calibration): <strong>${pAxes.epistemic_calibration?.baseline_mean?.toFixed(2)} → ${pAxes.epistemic_calibration?.candidate_mean?.toFixed(2)}</strong>（当前短板轴；unsupported_assertion 双臂 33 vs 33）</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">换位盲比 Pairwise v1 (21 对 × 2 序)</div>
          <div class="kpi-val">C胜 ${pwWins.candidate} · B胜 ${pwWins.baseline} · 平 ${pwWins.tie}</div>
          <div class="kpi-sub">正反一致率 <strong>${((17/21)*100).toFixed(1)}%</strong> · 拦截位置偏置 <strong>${pwWins.inc} 组</strong> (tie_position_inconsistent)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">人工审定队列 (Provisional)</div>
          <div class="kpi-val">${totalAdj} / ${totalJudged} 份建议复核</div>
          <div class="kpi-sub">全部 Judge 均为 <span class="mono">gpt-6.1-sol (medium)</span> 自动评审，未人工全量审定；可直接在下方记录你的裁决</div>
        </div>
      </div>
    `;
  }

  function renderMatrix() {
    const wrap = document.getElementById('matrix-container');
    if (!state.showMatrix) {
      wrap.style.display = 'none';
      return;
    }
    wrap.style.display = 'block';
    const rows = DATA.cases.map(c => {
      const bs = getV3Scores(c.arms.baseline);
      const cs = getV3Scores(c.arms.candidate);
      const b2 = c.arms.baseline?.judge_v2_1?.review?.quality_axes;
      const c2 = c.arms.candidate?.judge_v2_1?.review?.quality_axes;
      const fmt3 = s => s ? `<span class="sc ${scoreClass(s.t)}">${scoreLabel(s.t)}</span> <span class="sc ${scoreClass(s.g)}">${scoreLabel(s.g)}</span> <span class="sc ${scoreClass(s.c)}">${scoreLabel(s.c)}</span>` : `<span class="sc sc-fail">FAIL</span>`;
      const fmt2 = q => q ? `${q.task_satisfaction?.score}/${q.answer_reliability?.score}` : 'FAIL';
      const bp = getPriority(c.arms.baseline) || '-';
      const cp = getPriority(c.arms.candidate) || '-';
      const bDiag = c.arms.baseline?.judge_v3?.review?.diagnostics?.length ?? '-';
      const cDiag = c.arms.candidate?.judge_v3?.review?.diagnostics?.length ?? '-';
      return `
        <tr data-cid="${esc(c.case_id)}">
          <td class="mono"><strong>${esc(c.case_id)}</strong></td>
          <td>${esc(c.category)}</td>
          <td class="q-col">${esc(c.query)}</td>
          <td>${fmt3(bs)}</td>
          <td>${fmt3(cs)}</td>
          <td class="mono">${fmt2(b2)} → ${fmt2(c2)}</td>
          <td class="mono">${bDiag} → ${cDiag}</td>
          <td>${pairwiseBadgeHtml(c.pairwise)}</td>
          <td class="mono">${esc(bp)} / ${esc(cp)}</td>
        </tr>
      `;
    }).join('');

    wrap.innerHTML = `
      <div class="card">
        <div class="card-header">
          <div><strong>📊 全量 24 题 × 2 组 (48 次运行) 评分总览表</strong> <span class="muted">（点击任意行跳转详情 · T=任务满足 / G=事实忠实 / C=边界克制）</span></div>
          <button class="btn btn-sm" id="btn-hide-matrix">收起总览表</button>
        </div>
        <div class="matrix-wrap">
          <table class="matrix">
            <thead>
              <tr>
                <th>Case ID</th><th>分类</th><th>用户问题</th>
                <th>Baseline v3 (T/G/C)</th><th>Candidate v3 (T/G/C)</th>
                <th>v2.1 (T/R)</th><th>v3 诊断数</th><th>Pairwise 盲比</th><th>审定优先级 (B/C)</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>
    `;
    wrap.querySelector('#btn-hide-matrix').addEventListener('click', () => {
      state.showMatrix = false;
      renderMatrix();
    });
    wrap.querySelectorAll('tbody tr').forEach(tr => {
      tr.addEventListener('click', () => {
        state.selectedCaseId = tr.dataset.cid;
        state.showMatrix = false;
        renderMatrix();
        renderSidebar();
        renderCaseDetail();
      });
    });
  }

  function buildMessageLookup(evidenceThreads) {
    const map = {};
    for (const th of (evidenceThreads || [])) {
      for (const m of (th.messages || [])) {
        if (m.internal_message_id) map[m.internal_message_id] = m;
      }
    }
    return map;
  }

  function renderEvidenceDrawer(armKey, evidenceId, armObj) {
    const links = armObj.answer?.evidence_links || [];
    const link = links.find(x => x.evidence_id === evidenceId);
    const meta = armObj.answer?._artifact_evidence_meta?.[evidenceId];
    const msgMap = buildMessageLookup(armObj.judge_v3?.evidence_threads || []);
    if (!link) return '<div class="muted">未找到该引用条目。</div>';
    const srcIds = link.source_message_ids || [];
    const msgsHtml = srcIds.map(mid => {
      const m = msgMap[mid];
      if (!m) return `<div class="msg-row"><span class="mono muted">${esc(mid)} (未在 evidence_threads 中找到原文)</span></div>`;
      return `
        <div class="msg-row is-cited">
          <div class="msg-head">
            <span><span class="msg-sender">${esc(m.sender_display || m.sender_user_id)}</span> · <span>${esc(m.session_name || m.session_id)}</span></span>
            <span class="msg-time">${esc(m.timestamp_iso || fmtMsToIso(m.timestamp))}</span>
          </div>
          <div class="msg-body">${esc(m.content_text)}</div>
          <div class="msg-id">${esc(m.internal_message_id)}</div>
        </div>
      `;
    }).join('');
    return `
      <div style="margin-bottom:6px;">
        <span class="badge">${esc(evidenceId)}</span>
        <span class="badge">充分性: ${esc(link.sufficiency || '-')}</span>
        <span class="badge">绑定原文: ${srcIds.length} 条</span>
        ${meta?.finding ? `<div style="margin-top:5px;"><strong>系统归纳 (finding):</strong> ${esc(meta.finding)}</div>` : ''}
        ${meta?.criterion ? `<div class="muted" style="font-size:11.8px;"><strong>依据说明:</strong> ${esc(meta.criterion)}</div>` : ''}
        ${(link.limitations && link.limitations.length) ? `<div class="muted" style="font-size:11.8px;"><strong>该证据局限:</strong> ${esc(link.limitations.join('；'))}</div>` : ''}
      </div>
      ${msgsHtml || '<div class="muted">无绑定消息 ID（可能为结构化/SQL 来源）</div>'}
    `;
  }

  function renderAnswerSection(armKey, armObj) {
    if (armObj.summary?.terminal_status !== 'completed' || !armObj.answer) {
      const err = armObj.runtime?.error || {};
      const seq = (armObj.runtime?.tool_sequence || []).join(' → ') || '(无)';
      return `
        <div class="arm-section">
          <div class="section-heading">
            <div class="section-title">❌ 系统运行失败（未交付答案）</div>
          </div>
          <div class="failed-box">
            <div><strong>错误码:</strong> <span class="mono">${esc(err.code || armObj.summary?.error_type || 'UNKNOWN_FAILURE')}</span> · <strong>阶段:</strong> ${esc(err.stage || '-')} · <strong>类别:</strong> ${esc(err.category || '-')}</div>
            <div style="margin-top:4px;"><strong>说明:</strong> ${esc(err.message || armObj.summary?.runtime_error || '运行在交付最终答案前终止（例如 32K 工具结果预算耗尽）。')}</div>
            <div style="margin-top:4px;"><strong>已执行工具序列:</strong> <span class="mono">${esc(seq)}</span></div>
            ${Object.keys(err).length ? `<pre>${esc(JSON.stringify(err, null, 2))}</pre>` : ''}
          </div>
        </div>
      `;
    }

    const ans = armObj.answer;
    const blocks = ans.content_blocks || [];
    const bindingsMap = {};
    for (const b of (ans.citation_bindings || [])) {
      bindingsMap[b.content_block_id] = b.evidence_ids || [];
    }

    const blocksHtml = blocks.map((blk, idx) => {
      const eids = bindingsMap[blk.block_id] || [];
      const chipsHtml = eids.map(eid =>
        `<button class="cite-chip" data-arm="${armKey}" data-blk="${idx}" data-eid="${esc(eid)}" title="点击展开该引用的原始群聊消息">[${esc(eid)}]</button>`
      ).join('');
      return `
        <div class="answer-block" id="blk-${armKey}-${idx}" data-block-text="${esc(blk.text || '')}">
          <div class="block-meta">
            <span class="block-id">${esc(blk.block_id)}</span>
            <div class="cite-chips">${chipsHtml || '<span class="muted" style="font-size:11px;">无绑定引用</span>'}</div>
          </div>
          <div class="block-text">${esc(blk.text)}</div>
          <div class="cite-drawer" id="drawer-${armKey}-${idx}" style="display:none;"></div>
        </div>
      `;
    }).join('');

    const lims = ans.limitations || [];
    const limsHtml = lims.length ? `
      <div class="limitations-box">
        <strong>系统自述局限性 (limitations · ${lims.length} 条):</strong>
        <ul>${lims.map(l => `<li>${esc(l)}</li>`).join('')}</ul>
      </div>
    ` : '';

    return `
      <div class="arm-section">
        <div class="section-heading">
          <div class="section-title">💬 被测系统回答 (${blocks.length} 段)</div>
          <span class="muted" style="font-size:11.5px;">点击 <span class="mono">[e1]</span> 标签可就地查看绑定的原始群聊消息</span>
        </div>
        ${blocksHtml}
        ${limsHtml}
      </div>
    `;
  }

  function renderJudgeSection(armKey, armObj) {
    if (!armObj.judge_v3 && !armObj.judge_v2_1) {
      return `
        <div class="arm-section">
          <div class="section-heading"><div class="section-title">🧑‍⚖️ LLM Judge 评分与评论</div></div>
          <div class="muted">本次运行未交付答案，因此未送入 LLM Judge 评分。</div>
        </div>
      `;
    }

    const activeTab = state.rubricTab[armKey] || 'v3';
    const jObj = activeTab === 'v3' ? armObj.judge_v3 : armObj.judge_v2_1;
    const rev = jObj?.review;
    if (!rev) return '';

    const axesEntries = Object.entries(rev.quality_axes || {});
    const axesHtml = axesEntries.map(([axisKey, axisVal]) => `
      <div class="axis-card">
        <div class="axis-top">
          <span class="axis-name">${esc(AXIS_CN[axisKey] || axisKey)}</span>
          <span class="axis-score-big ${scoreClass(axisVal.score)}">${esc(axisVal.score === 'unknown' ? 'unknown' : `${axisVal.score} / 4`)}</span>
        </div>
        <div class="axis-reason">${esc(axisVal.reason)}</div>
      </div>
    `).join('');

    const diags = rev.diagnostics || [];
    const diagsHtml = diags.length ? diags.map((d, di) => `
      <div class="diag-card sev-${esc(d.severity || 'minor')}">
        <div class="diag-header">
          <div style="display:flex;gap:5px;flex-wrap:wrap;align-items:center;">
            <span class="badge ${d.severity === 'severe' ? 'badge-high' : d.severity === 'moderate' ? 'badge-medium' : ''}">${esc(d.severity)}</span>
            <span class="badge">${esc(DIAG_CN[d.type] || d.type)} (${esc(d.type)})</span>
            <span class="badge badge-purple">${esc(d.primary_dimension)}</span>
          </div>
          ${d.answer_excerpt ? `<button class="btn btn-sm btn-locate-excerpt" data-arm="${armKey}" data-excerpt="${esc(d.answer_excerpt)}">🎯 定位正文</button>` : ''}
        </div>
        ${d.answer_excerpt ? `<div class="diag-field"><span class="diag-field-label">问题摘录:</span><span class="diag-excerpt">「${esc(d.answer_excerpt)}」</span></div>` : '<div class="diag-field muted"><span class="diag-field-label">问题摘录:</span>无（遗漏型问题）</div>'}
        <div class="diag-field"><span class="diag-field-label">核验依据 (evidence):</span>${esc(d.evidence)}</div>
        <div class="diag-field"><span class="diag-field-label">用户影响 (impact):</span>${esc(d.impact)}</div>
      </div>
    `).join('') : '<div class="muted" style="padding:8px 0;">无具体缺陷诊断（diagnostics 为空）。</div>';

    const prio = rev.adjudication_priority;
    const prioBadge = prio ? `<span class="badge badge-${esc(prio)}">审定优先级: ${esc(prio)}</span>` : '';
    const adjBadge = rev.needs_adjudication ? `<span class="badge badge-medium">needs_adjudication=true</span>` : `<span class="badge badge-none">needs_adjudication=false</span>`;
    const usage = jObj.usage || {};

    return `
      <div class="arm-section">
        <div class="section-heading">
          <div class="section-title">🧑‍⚖️ LLM Judge 评分与评论</div>
          <div class="sub-tabs" style="margin:0;">
            <button class="sub-tab btn-rubric-tab ${activeTab === 'v3' ? 'active' : ''}" data-arm="${armKey}" data-rubric="v3">v3 三维 (最新)</button>
            <button class="sub-tab btn-rubric-tab ${activeTab === 'v2_1' ? 'active' : ''}" data-arm="${armKey}" data-rubric="v2_1">v2.1 双维 (对照)</button>
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;align-items:center;">
          <span class="badge mono">${esc(jObj.model || 'gpt-6.1-sol')} · ${esc(rev.rubric_version)}</span>
          ${prioBadge}
          ${adjBadge}
          <span class="badge mono">输入 ${fmtNum(usage.input_tokens)} tok · 输出 ${fmtNum(usage.output_tokens)} tok</span>
        </div>
        <div class="axes-grid">${axesHtml}</div>
        <div class="judge-notes">
          <strong>总体评语 (notes / overall_rationale):</strong><br/>
          ${esc(rev.notes)}
        </div>
        <div style="font-size:12.5px;font-weight:700;margin-bottom:6px;">🔍 缺陷诊断明细 (diagnostics · ${diags.length} 条)</div>
        ${diagsHtml}
      </div>
    `;
  }

  function renderJudgeContextSection(armKey, armObj, caseObj) {
    if (!armObj.judge_v3) return '';
    const j3 = armObj.judge_v3;
    const j2 = armObj.judge_v2_1;
    const ts = j3.thread_stats || {};
    const cTab = state.contextTab[armKey] || 'threads';
    const onlyCited = Boolean(state.threadOnlyCited[armKey]);
    const tSearch = (state.threadSearch[armKey] || '').trim().toLowerCase();

    const sizeCompare = j2 && j2.input_chars
      ? `v3 输入 <strong>${fmtNum(j3.input_chars)} 字符</strong> (${fmtNum(j3.usage?.input_tokens)} tok) vs v2.1 <strong>${fmtNum(j2.input_chars)} 字符</strong> (${fmtNum(j2.usage?.input_tokens)} tok)`
      : `v3 输入 <strong>${fmtNum(j3.input_chars)} 字符</strong> (${fmtNum(j3.usage?.input_tokens)} tok)`;

    let bodyHtml = '';
    if (cTab === 'threads') {
      const threads = j3.evidence_threads || [];
      const threadsHtml = threads.map((th, ti) => {
        const msgs = (th.messages || []).filter(m => {
          if (onlyCited && !m.is_cited && !m.is_reply_target) return false;
          if (tSearch) {
            const hay = `${m.sender_display||''} ${m.content_text||''} ${m.internal_message_id||''} ${m.timestamp_iso||''}`.toLowerCase();
            if (!hay.includes(tSearch)) return false;
          }
          return true;
        });
        const citedInThread = (th.messages || []).filter(m => m.is_cited).length;
        const rowsHtml = msgs.map(m => {
          const cls = m.is_cited ? 'is-cited' : (m.is_reply_target ? 'is-reply-target' : '');
          const tags = [
            m.is_cited ? '<span class="badge badge-low">✓ 回答引用</span>' : '',
            m.is_reply_target ? '<span class="badge badge-purple">↩ 远回复目标</span>' : '',
            m.is_forwarded ? '<span class="badge">📨 转发内嵌</span>' : '',
            m.reply_to_internal_message_id ? `<span class="muted mono" style="font-size:10.5px;">回复→${esc(m.reply_to_internal_message_id.split(':').pop())}</span>` : '',
          ].filter(Boolean).join(' ');
          return `
            <div class="msg-row ${cls}">
              <div class="msg-head">
                <span><span class="msg-sender">${esc(m.sender_display || m.sender_user_id)}</span> ${tags}</span>
                <span class="msg-time">${esc(m.timestamp_iso || fmtMsToIso(m.timestamp))}</span>
              </div>
              <div class="msg-body">${esc(m.content_text)}</div>
              <div class="msg-id">${esc(m.internal_message_id)}</div>
            </div>
          `;
        }).join('');
        return `
          <details class="thread-box" ${ti === 0 ? 'open' : ''}>
            <summary class="thread-header">
              <span>💬 ${esc(th.session_name || th.session_id)} <span class="muted mono" style="font-weight:400;">(${esc(th.session_id)})</span></span>
              <span class="muted" style="font-weight:500;">显示 ${msgs.length} / 共 ${(th.messages||[]).length} 条 · 其中被引用 ${citedInThread} 条</span>
            </summary>
            <div class="thread-messages">${rowsHtml || '<div class="muted" style="padding:10px;">当前筛选条件下无消息</div>'}</div>
          </details>
        `;
      }).join('');

      bodyHtml = `
        <div class="flex-between mb-8">
          <label style="font-size:12px;cursor:pointer;display:flex;align-items:center;gap:5px;">
            <input type="checkbox" class="chk-only-cited" data-arm="${armKey}" ${onlyCited ? 'checked' : ''} />
            仅显示被引用消息 & 远回复目标（隐藏普通 ±3 邻居）
          </label>
          <input type="text" class="search-input input-thread-search" data-arm="${armKey}" value="${esc(state.threadSearch[armKey] || '')}" placeholder="在时间线中搜发言人或关键词..." style="width:220px;padding:4px 8px;font-size:12px;" />
        </div>
        ${threadsHtml || '<div class="muted">无 evidence_threads。</div>'}
      `;
    } else if (cTab === 'answer_struct') {
      const cleanAnswer = { ...armObj.answer };
      delete cleanAnswer._artifact_evidence_meta;
      bodyHtml = `
        <div class="limitations-box mb-8">
          <strong>传给 Judge 的输入层限制声明 (input.limitations):</strong>
          <div style="margin-top:4px;">${esc(j3.limitations || '')}</div>
        </div>
        <div style="font-size:12px;font-weight:700;margin-bottom:6px;">传给 Judge 的 answer 结构（已剥离重复 snapshot，保留无损 content_blocks + citation_bindings + 精简 evidence_links）:</div>
        <pre class="code-pre">${esc(JSON.stringify(cleanAnswer, null, 2))}</pre>
      `;
    } else {
      const cleanAnswer = { ...armObj.answer };
      delete cleanAnswer._artifact_evidence_meta;
      const reconstructedInput = {
        case_id: caseObj.case_id,
        case_version: caseObj.case_version,
        as_of: caseObj.as_of,
        query: caseObj.query,
        ground_truth: caseObj.ground_truth,
        reference_evidence: caseObj.reference_evidence,
        answer: cleanAnswer,
        evidence_threads: j3.evidence_threads,
        limitations: j3.limitations,
      };
      bodyHtml = `
        <div class="flex-between mb-8">
          <span class="muted" style="font-size:12px;">以下为实际通过 <span class="mono">user_prompt</span> 发给 LLM Judge (v3) 的完整 JSON（已按原字段顺序重组）：</span>
          <button class="btn btn-sm btn-copy-raw" data-arm="${armKey}">📋 复制完整 input.json</button>
        </div>
        <pre class="code-pre" id="raw-json-${armKey}">${esc(JSON.stringify(reconstructedInput, null, 2))}</pre>
      `;
    }

    return `
      <div class="arm-section">
        <div class="section-heading">
          <div class="section-title">📥 传给 LLM Judge 的实际上下文 (v3 input.json)</div>
          <div class="sub-tabs" style="margin:0;">
            <button class="sub-tab btn-ctx-tab ${cTab === 'threads' ? 'active' : ''}" data-arm="${armKey}" data-ctx="threads">原始证据时间线 (${ts.total_messages || 0}条)</button>
            <button class="sub-tab btn-ctx-tab ${cTab === 'answer_struct' ? 'active' : ''}" data-arm="${armKey}" data-ctx="answer_struct">传给 Judge 的 Answer 结构</button>
            <button class="sub-tab btn-ctx-tab ${cTab === 'raw' ? 'active' : ''}" data-arm="${armKey}" data-ctx="raw">完整 Raw JSON</button>
          </div>
        </div>
        <div class="context-stats">
          <span>📦 ${sizeCompare}</span>
          <span>🗂️ <strong>${ts.sessions || 0}</strong> 个群聊线程</span>
          <span>✓ 引用消息 <strong>${ts.cited_messages || 0}</strong> · ±3 邻居 <strong>${ts.neighbor_messages || 0}</strong> · 远回复目标 <strong>${ts.reply_target_messages || 0}</strong></span>
          <span>📚 附带开放 GT + <strong>${(caseObj.reference_evidence || []).length}</strong> 条参考证据（可在顶部「题目参考基准」页查看）</span>
        </div>
        ${bodyHtml}
      </div>
    `;
  }

  function renderHumanAuditSection(armKey, caseId) {
    const saved = getAudit(caseId, armKey) || {};
    const scoreOpts = val => ['', '4', '3', '2', '1', '0', 'unknown'].map(opt =>
      `<option value="${opt}" ${String(val ?? '') === opt ? 'selected' : ''}>${opt === '' ? '不改判' : opt}</option>`
    ).join('');
    return `
      <div class="arm-section">
        <div class="human-audit-box" data-audit-arm="${armKey}">
          <div class="flex-between">
            <strong style="font-size:13px;">✍️ 我的人工审核 (${armKey === 'baseline' ? 'Baseline' : 'Candidate'})</strong>
            <span class="muted" style="font-size:11.5px;">自动保存在本机浏览器 localStorage</span>
          </div>
          <div class="verdict-row">
            <button class="verdict-btn ${saved.verdict === 'agree' ? 'active-agree' : ''}" data-arm="${armKey}" data-verdict="agree">✅ 同意 Judge</button>
            <button class="verdict-btn ${saved.verdict === 'partial' ? 'active-partial' : ''}" data-arm="${armKey}" data-verdict="partial">⚠️ 部分分歧</button>
            <button class="verdict-btn ${saved.verdict === 'disagree' ? 'active-disagree' : ''}" data-arm="${armKey}" data-verdict="disagree">❌ 不同意 Judge</button>
          </div>
          <div class="human-scores">
            <label>人工改判 T: <select class="sel-hscore" data-arm="${armKey}" data-axis="t">${scoreOpts(saved.t)}</select></label>
            <label>G: <select class="sel-hscore" data-arm="${armKey}" data-axis="g">${scoreOpts(saved.g)}</select></label>
            <label>C: <select class="sel-hscore" data-arm="${armKey}" data-axis="c">${scoreOpts(saved.c)}</select></label>
          </div>
          <textarea class="human-note" data-arm="${armKey}" placeholder="写下你的审核意见（例如：Judge 判得偏严/偏松、某条引用其实合理、系统遗漏了关键群聊等）...">${esc(saved.note || '')}</textarea>
        </div>
      </div>
    `;
  }

  function renderArmPanel(armKey, armObj, caseObj) {
    const s = armObj.summary || {};
    const tel = s.telemetry || {};
    const usage = s.usage || {};
    const isOk = s.terminal_status === 'completed';
    const titleLabel = armKey === 'baseline'
      ? '🅰️ Baseline（旧排序 + 无引号修复）'
      : '🅱️ Candidate（当前 main：相关性保留 + 引号容错）';
    const quoteBadge = tel.quote_repaired ? `<span class="badge badge-cwin">🔧 修复 ${tel.quote_repair_count} 处引号</span>` : '';
    const budgetBadge = tel.budget_errors ? `<span class="badge badge-medium">⚠️ 预算错误 ×${tel.budget_errors}</span>` : '';
    const toolSeq = (armObj.runtime?.tool_sequence || []).join(' → ') || '-';

    return `
      <div class="arm-panel">
        <div class="arm-header ${armKey}">
          <div class="arm-title">
            <span>${titleLabel}</span>
            <span class="badge ${isOk ? 'badge-none' : 'badge-high'}">${isOk ? 'completed' : 'FAILED'}</span>
            ${quoteBadge}${budgetBadge}
          </div>
          <span class="mono muted" style="font-size:11.5px;">${esc(s.latency_seconds)}s · ${fmtNum(usage.input_tokens)} in / ${fmtNum(usage.output_tokens)} out</span>
        </div>
        <div class="telemetry-bar">
          <span>route=${esc(armObj.runtime?.route || '-')}</span>
          <span>rounds=${esc(armObj.runtime?.tool_rounds ?? '-')}</span>
          <span>tools(${esc(tel.tool_calls_total ?? 0)})=${esc(toolSeq)}</span>
        </div>
        ${renderAnswerSection(armKey, armObj)}
        ${renderJudgeSection(armKey, armObj)}
        ${renderJudgeContextSection(armKey, armObj, caseObj)}
        ${renderHumanAuditSection(armKey, caseObj.case_id)}
      </div>
    `;
  }

  function renderPairwiseView(caseObj) {
    const pw = caseObj.pairwise;
    if (!pw) {
      return `<div class="card"><div class="card-body muted">本题因至少一侧运行失败，未参与双臂配对换位盲比（Pairwise v1）。</div></div>`;
    }
    const agg = pw.aggregated || {};
    const renderRunCard = (title, runObj, usage) => {
      if (!runObj) return '';
      const axesHtml = Object.entries(runObj.axes || {}).map(([k, v]) => `
        <div class="axis-card">
          <div class="axis-top">
            <span class="axis-name">${esc(AXIS_CN[k] || k)}</span>
            <span class="badge ${v.winner_arm === 'candidate' ? 'badge-cwin' : v.winner_arm === 'baseline' ? 'badge-bwin' : 'badge-tie'}">
              原始选 ${esc(v.raw_winner)} → ${esc(v.winner_arm)}
            </span>
          </div>
          <div class="axis-reason">${esc(v.reason)}</div>
        </div>
      `).join('');
      const diffs = (runObj.key_differences || []).map(x => `<li>${esc(x)}</li>`).join('');
      return `
        <div class="card">
          <div class="card-header">
            <div><strong>${title}</strong> <span class="mono muted">(A=${esc(runObj.arm_a)}, B=${esc(runObj.arm_b)})</span></div>
            <span class="badge ${runObj.overall_winner_arm === 'candidate' ? 'badge-cwin' : runObj.overall_winner_arm === 'baseline' ? 'badge-bwin' : 'badge-tie'}">
              本序胜者: ${esc(runObj.raw_overall_winner)} (${esc(runObj.overall_winner_arm)})
            </span>
          </div>
          <div class="card-body">
            <div class="judge-notes"><strong>综合理由:</strong><br/>${esc(runObj.overall_rationale)}</div>
            <div class="axes-grid">${axesHtml}</div>
            ${diffs ? `<div class="limitations-box"><strong>关键差异 (key_differences):</strong><ul>${diffs}</ul></div>` : ''}
            <div class="muted mono mt-8" style="font-size:11.5px;">输入 ${fmtNum(usage?.input_tokens)} tok · 输出 ${fmtNum(usage?.output_tokens)} tok</div>
          </div>
        </div>
      `;
    };

    const aggAxesHtml = Object.entries(agg.axes || {}).map(([k, v]) => `
      <span class="badge ${v.winner === 'candidate' ? 'badge-cwin' : v.winner === 'baseline' ? 'badge-bwin' : v.consistent === false ? 'badge-inconsistent' : 'badge-tie'}">
        ${esc(k)}: ${esc(v.winner)} (${v.consistent ? '一致' : '换位冲突'})
      </span>
    `).join(' ');

    return `
      <div class="card mb-8">
        <div class="card-header">
          <div>
            <strong>⚖️ 换位去偏盲比汇总 (eval-pairwise-v1)</strong>
            <div class="muted" style="font-size:12px;">同一份共享证据时间线上匿名比较 A/B，并交换位置重评一次以拦截位置偏置 · 单序输入 ${fmtNum(pw.input_chars)} 字符</div>
          </div>
          <div>${pairwiseBadgeHtml(pw)}</div>
        </div>
        <div class="card-body">
          <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
            <span><strong>正反序是否一致:</strong> ${agg.overall_consistent ? '✅ 一致' : '⚠️ 不一致（已判 tie_position_inconsistent）'}</span>
            ${aggAxesHtml}
          </div>
        </div>
      </div>
      <div class="ab-grid">
        ${renderRunCard('正序盲比 (Forward: A=Baseline, B=Candidate)', pw.forward_ab, pw.forward_usage)}
        ${renderRunCard('反序盲比 (Reverse: A=Candidate, B=Baseline)', pw.reverse_ba, pw.reverse_usage)}
      </div>
    `;
  }

  function renderGtView(caseObj) {
    const gt = caseObj.ground_truth || {};
    const facts = (gt.candidate_facts || []).map((f, i) => `
      <div class="axis-card">
        <div class="axis-top">
          <span class="axis-name">参考事实 #${i + 1}</span>
          <span class="badge">${esc(f.epistemic_type || '-')}</span>
        </div>
        <div class="axis-reason">${esc(f.claim)}</div>
        ${(f.message_ids && f.message_ids.length) ? `<div class="msg-id mt-8">关联消息: ${esc(f.message_ids.join(', '))}</div>` : ''}
      </div>
    `).join('');

    const refEv = (caseObj.reference_evidence || []).map((ev, i) => {
      const ctxMsgs = (ev.context || []).map(cm => `
        <div class="msg-row ${cm.internal_message_id === ev.internal_message_id ? 'is-cited' : ''}">
          <div class="msg-head">
            <span class="msg-sender">${esc(cm.sender_display || cm.sender_user_id)}</span>
            <span class="msg-time">${esc(cm.timestamp_iso || fmtMsToIso(cm.timestamp))}</span>
          </div>
          <div class="msg-body">${esc(cm.content_text)}</div>
          <div class="msg-id">${esc(cm.internal_message_id)}</div>
        </div>
      `).join('');
      return `
        <details class="thread-box" ${i < 2 ? 'open' : ''}>
          <summary class="thread-header">
            <span>📌 参考证据 #${i + 1} · ${esc(ev.session_name || ev.session_id)} (${esc(ev.timestamp_iso || fmtMsToIso(ev.timestamp))})</span>
            <span class="muted mono" style="font-weight:400;">${esc(ev.internal_message_id)}</span>
          </summary>
          <div class="thread-messages">
            <div class="msg-row is-cited">
              <div class="msg-head"><span><strong>核心参考消息</strong> · ${esc(ev.sender_display || ev.sender_user_id)}</span><span class="msg-time">${esc(ev.timestamp_iso || fmtMsToIso(ev.timestamp))}</span></div>
              <div class="msg-body">${esc(ev.content_text)}</div>
            </div>
            ${ctxMsgs ? `<div class="muted" style="font-size:11.5px;margin:6px 0 4px;">附带上下文 (${(ev.context||[]).length} 条):</div>${ctxMsgs}` : ''}
          </div>
        </details>
      `;
    }).join('');

    return `
      <div class="card">
        <div class="card-header">
          <div>
            <strong>📚 题目开放式 Ground Truth 与参考证据（一并传给 LLM Judge）</strong>
            <div class="muted" style="font-size:12px;">注意：Judge 明确被告知 GT 不是穷尽清单，系统从库中合法回读的其他有效原文同样被接受。</div>
          </div>
          <span class="badge">${esc(gt.gt_version || 'eval-gt-v1')} · 证据状态: ${esc(gt.evidence_status || '-')}</span>
        </div>
        <div class="card-body">
          <div class="meta-grid mb-8">
            <div class="meta-item"><strong>用户真实需求 (user_need):</strong> ${esc(gt.user_need)}</div>
            <div class="meta-item"><strong>必答要点 (must_answer):</strong> ${esc(gt.must_answer)}</div>
          </div>
          <div class="limitations-box mb-8">
            <div><strong>证据边界提示 (evidence_limitations):</strong> ${esc(gt.evidence_limitations)}</div>
            <div style="margin-top:5px;"><strong>其他合理答案说明 (reasonable_other_answers):</strong> ${esc(gt.reasonable_other_answers)}</div>
            ${gt.conflicts_and_uncertainty ? `<div style="margin-top:5px;"><strong>分歧与不确定性:</strong> ${esc(typeof gt.conflicts_and_uncertainty === 'string' ? gt.conflicts_and_uncertainty : JSON.stringify(gt.conflicts_and_uncertainty))}</div>` : ''}
          </div>
          <div style="font-size:13px;font-weight:700;margin:12px 0 6px;">候选参考事实 (candidate_facts · ${(gt.candidate_facts||[]).length} 条)</div>
          <div class="axes-grid">${facts}</div>
          <div style="font-size:13px;font-weight:700;margin:14px 0 6px;">参考原始证据 (reference_evidence · ${(caseObj.reference_evidence||[]).length} 条)</div>
          ${refEv || '<div class="muted">无参考证据</div>'}
        </div>
      </div>
    `;
  }

  function renderCaseDetail() {
    const container = document.getElementById('case-detail-container');
    const c = DATA.cases.find(x => x.case_id === state.selectedCaseId);
    if (!c) {
      container.innerHTML = '<div class="card"><div class="card-body muted">请在左侧选择一道题目。</div></div>';
      return;
    }
    const idx = DATA.cases.findIndex(x => x.case_id === c.case_id);
    const gt = c.ground_truth || {};

    let contentHtml = '';
    if (state.viewMode === 'ab') {
      contentHtml = `<div class="ab-grid">${renderArmPanel('baseline', c.arms.baseline, c)}${renderArmPanel('candidate', c.arms.candidate, c)}</div>`;
    } else if (state.viewMode === 'baseline') {
      contentHtml = `<div class="ab-grid single-col">${renderArmPanel('baseline', c.arms.baseline, c)}</div>`;
    } else if (state.viewMode === 'candidate') {
      contentHtml = `<div class="ab-grid single-col">${renderArmPanel('candidate', c.arms.candidate, c)}</div>`;
    } else if (state.viewMode === 'pairwise') {
      contentHtml = renderPairwiseView(c);
    } else {
      contentHtml = renderGtView(c);
    }

    container.innerHTML = `
      <div class="card">
        <div class="card-header">
          <div style="flex:1;min-width:260px;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <span class="badge mono">${idx + 1} / ${DATA.cases.length}</span>
              <span class="badge mono">${esc(c.case_id)} @v${esc(c.case_version)}</span>
              <span class="badge">${esc(c.category)}</span>
              ${pairwiseBadgeHtml(c.pairwise)}
            </div>
            <div class="question-title">${esc(c.query)}</div>
            <div class="meta-grid">
              <div class="meta-item"><strong>查询时点 (as_of):</strong> <span class="mono">${esc(c.as_of?.as_of || '-')}</span></div>
              <div class="meta-item"><strong>数据截止:</strong> <span class="mono">${esc(c.as_of?.data_cutoff || '-')}</span></div>
              <div class="meta-item"><strong>用户需求:</strong> ${esc(gt.user_need || '-')}</div>
            </div>
          </div>
          <div style="display:flex;flex-direction:column;gap:8px;align-items:flex-end;">
            <div style="display:flex;gap:6px;">
              <button class="btn btn-sm" id="btn-prev-case" ${idx <= 0 ? 'disabled' : ''}>← 上一题</button>
              <button class="btn btn-sm" id="btn-next-case" ${idx >= DATA.cases.length - 1 ? 'disabled' : ''}>下一题 →</button>
            </div>
            <div class="tabs">
              <button class="tab-btn ${state.viewMode === 'ab' ? 'active' : ''}" data-mode="ab">🔀 A/B 并排</button>
              <button class="tab-btn ${state.viewMode === 'baseline' ? 'active' : ''}" data-mode="baseline">🅰️ 仅 Baseline</button>
              <button class="tab-btn ${state.viewMode === 'candidate' ? 'active' : ''}" data-mode="candidate">🅱️ 仅 Candidate</button>
              <button class="tab-btn ${state.viewMode === 'pairwise' ? 'active' : ''}" data-mode="pairwise">⚖️ 换位盲比</button>
              <button class="tab-btn ${state.viewMode === 'gt' ? 'active' : ''}" data-mode="gt">📚 参考基准 (GT)</button>
            </div>
          </div>
        </div>
      </div>
      ${contentHtml}
    `;

    // Bind navigation & view tabs
    container.querySelector('#btn-prev-case')?.addEventListener('click', () => {
      if (idx > 0) { state.selectedCaseId = DATA.cases[idx - 1].case_id; renderSidebar(); renderCaseDetail(); }
    });
    container.querySelector('#btn-next-case')?.addEventListener('click', () => {
      if (idx < DATA.cases.length - 1) { state.selectedCaseId = DATA.cases[idx + 1].case_id; renderSidebar(); renderCaseDetail(); }
    });
    container.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        state.viewMode = btn.dataset.mode;
        renderCaseDetail();
      });
    });

    // Bind citation chips
    container.querySelectorAll('.cite-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const armKey = chip.dataset.arm;
        const blkIdx = chip.dataset.blk;
        const eid = chip.dataset.eid;
        const drawer = container.querySelector(`#drawer-${armKey}-${blkIdx}`);
        if (!drawer) return;
        const isSame = drawer.style.display === 'block' && drawer.dataset.activeEid === eid;
        container.querySelectorAll(`#blk-${armKey}-${blkIdx} .cite-chip`).forEach(x => x.classList.remove('open'));
        if (isSame) {
          drawer.style.display = 'none';
          drawer.dataset.activeEid = '';
        } else {
          chip.classList.add('open');
          drawer.dataset.activeEid = eid;
          drawer.innerHTML = renderEvidenceDrawer(armKey, eid, c.arms[armKey]);
          drawer.style.display = 'block';
        }
      });
    });

    // Bind Judge rubric toggle (v3 vs v2.1)
    container.querySelectorAll('.btn-rubric-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        state.rubricTab[btn.dataset.arm] = btn.dataset.rubric;
        renderCaseDetail();
      });
    });

    // Bind Judge context sub-tabs
    container.querySelectorAll('.btn-ctx-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        state.contextTab[btn.dataset.arm] = btn.dataset.ctx;
        renderCaseDetail();
      });
    });

    // Bind thread filters
    container.querySelectorAll('.chk-only-cited').forEach(chk => {
      chk.addEventListener('change', () => {
        state.threadOnlyCited[chk.dataset.arm] = chk.checked;
        renderCaseDetail();
      });
    });
    container.querySelectorAll('.input-thread-search').forEach(inp => {
      inp.addEventListener('input', () => {
        state.threadSearch[inp.dataset.arm] = inp.value;
        const pos = inp.selectionStart;
        const arm = inp.dataset.arm;
        renderCaseDetail();
        const fresh = document.querySelector(`.input-thread-search[data-arm="${arm}"]`);
        if (fresh) { fresh.focus(); fresh.setSelectionRange(pos, pos); }
      });
    });

    // Bind locate excerpt button
    container.querySelectorAll('.btn-locate-excerpt').forEach(btn => {
      btn.addEventListener('click', () => {
        const arm = btn.dataset.arm;
        const excerpt = (btn.dataset.excerpt || '').trim();
        const blocks = container.querySelectorAll(`[id^="blk-${arm}-"]`);
        let found = null;
        const probe = excerpt.slice(0, Math.min(excerpt.length, 24));
        for (const blk of blocks) {
          if ((blk.dataset.blockText || '').includes(probe)) { found = blk; break; }
        }
        if (found) {
          found.scrollIntoView({ behavior: 'smooth', block: 'center' });
          found.classList.remove('highlight-pulse');
          void found.offsetWidth;
          found.classList.add('highlight-pulse');
          setTimeout(() => found.classList.remove('highlight-pulse'), 2800);
        } else {
          alert('未能在正文段落中精确匹配该摘录（可能跨段落或经过转述）。');
        }
      });
    });

    // Bind Copy Raw JSON
    container.querySelectorAll('.btn-copy-raw').forEach(btn => {
      btn.addEventListener('click', async () => {
        const pre = container.querySelector(`#raw-json-${btn.dataset.arm}`);
        if (!pre) return;
        try {
          await navigator.clipboard.writeText(pre.textContent);
          const orig = btn.textContent;
          btn.textContent = '✅ 已复制';
          setTimeout(() => { btn.textContent = orig; }, 1500);
        } catch { alert('复制失败，请手动选中复制。'); }
      });
    });

    // Bind Human Audit inputs
    container.querySelectorAll('.verdict-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const arm = btn.dataset.arm;
        const key = auditKey(c.case_id, arm);
        const cur = state.humanAudit[key] || {};
        cur.verdict = cur.verdict === btn.dataset.verdict ? '' : btn.dataset.verdict;
        cur.updated_at = new Date().toISOString();
        state.humanAudit[key] = cur;
        saveHumanAudit();
        renderSidebar();
        renderCaseDetail();
      });
    });
    container.querySelectorAll('.sel-hscore').forEach(sel => {
      sel.addEventListener('change', () => {
        const arm = sel.dataset.arm;
        const axis = sel.dataset.axis;
        const key = auditKey(c.case_id, arm);
        const cur = state.humanAudit[key] || {};
        cur[axis] = sel.value;
        cur.updated_at = new Date().toISOString();
        state.humanAudit[key] = cur;
        saveHumanAudit();
      });
    });
    container.querySelectorAll('.human-note').forEach(ta => {
      ta.addEventListener('input', () => {
        const arm = ta.dataset.arm;
        const key = auditKey(c.case_id, arm);
        const cur = state.humanAudit[key] || {};
        cur.note = ta.value;
        cur.updated_at = new Date().toISOString();
        state.humanAudit[key] = cur;
        saveHumanAudit();
      });
    });
  }

  function renderPromptModal() {
    const body = document.getElementById('prompt-modal-body');
    const prompts = DATA.prompts || {};
    body.innerHTML = `
      <div class="limitations-box mb-8">
        <div style="font-size:13.5px;font-weight:700;color:var(--text);margin-bottom:6px;">一、每次调用 LLM Judge 时，系统到底传了什么上下文？</div>
        <p style="margin:4px 0;">离线裁判模型为 <span class="mono">chatgpt-plan / gpt-6.1-sol (medium)</span>，通过 <span class="mono">complete_json(system_prompt, user_prompt)</span> 单轮无工具调用完成评分。</p>
        <ul style="margin:6px 0 6px 18px;">
          <li><strong>System Prompt：</strong>下方完整展示的评分准则（<span class="mono">eval-rubric-v3</span> / <span class="mono">eval-rubric-v2.1</span> / <span class="mono">eval-pairwise-v1</span>）。</li>
          <li><strong>User Prompt (JSON)：</strong>包含 7 个顶层字段——<span class="mono">query</span>（原始问题）、<span class="mono">as_of</span>（查询时点与数据截止时间）、<span class="mono">ground_truth</span>（开放式参考事实，明确非穷尽）、<span class="mono">reference_evidence</span>（参考消息及其上下文）、<span class="mono">answer</span>（被测系统的 <span class="mono">content_blocks</span> + <span class="mono">citation_bindings</span> + 精简 <span class="mono">evidence_links</span> + <span class="mono">limitations</span>）、<span class="mono">evidence_threads</span>（<strong>所有被回答引用的消息从 864k 冻结库重新回读</strong>，补齐前后 ±3 条邻居、跨窗口远距离回复目标、可读时间 <span class="mono">timestamp_iso</span> 与群友显示名 <span class="mono">sender_display</span>，并按群聊去重排时间线）、以及 <span class="mono">limitations</span>（输入层边界声明）。</li>
          <li><strong>明确不传给 Judge 的信息（盲评隔离）：</strong>不传 Baseline/Candidate 分组名、不传被测 Agent 的中间思考/工具 Trace、<strong>不重新执行 SQL</strong>（若回答核心依赖 SQL 数值统计且原文无法验证，v3 要求给 <span class="mono">unknown</span>）。</li>
          <li><strong>v3 相比 v2.1 的输入升级：</strong>修复了 v2.1 的 3 处盲区（原始 Unix 毫秒戳 → <span class="mono">timestamp_iso</span>；邻居缺发言人名 → 100% 补齐 <span class="mono">sender_display</span>；±3 窗口外远回复断裂 → 自动回读 <span class="mono">is_reply_target</span>），同时合并去重重叠上下文并剥离重复 snapshot，使输入字符数中位数下降 <strong>45.8%</strong>、Token 下降 <strong>25.3%</strong>。</li>
        </ul>
      </div>
      <div class="sub-tabs" id="modal-prompt-tabs">
        <button class="sub-tab active" data-pkey="eval-rubric-v3">eval-rubric-v3 (三正交维度 · 最新)</button>
        <button class="sub-tab" data-pkey="eval-rubric-v2.1">eval-rubric-v2.1 (双维度 · 历史对照)</button>
        <button class="sub-tab" data-pkey="eval-pairwise-v1">eval-pairwise-v1 (换位匿名盲比)</button>
      </div>
      <pre class="code-pre" id="modal-prompt-pre">${esc(prompts['eval-rubric-v3'] || '')}</pre>
    `;
    body.querySelectorAll('#modal-prompt-tabs .sub-tab').forEach(btn => {
      btn.addEventListener('click', () => {
        body.querySelectorAll('#modal-prompt-tabs .sub-tab').forEach(x => x.classList.remove('active'));
        btn.classList.add('active');
        body.querySelector('#modal-prompt-pre').textContent = prompts[btn.dataset.pkey] || '';
      });
    });
  }

  // Global bindings
  document.getElementById('search-box').addEventListener('input', e => {
    state.search = e.target.value;
    renderSidebar();
  });
  document.getElementById('filter-pills').addEventListener('click', e => {
    const pill = e.target.closest('.pill');
    if (!pill) return;
    document.querySelectorAll('#filter-pills .pill').forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    state.filter = pill.dataset.filter;
    renderSidebar();
  });
  document.getElementById('btn-toggle-matrix').addEventListener('click', () => {
    state.showMatrix = !state.showMatrix;
    renderMatrix();
  });
  document.getElementById('btn-open-prompt-modal').addEventListener('click', () => {
    renderPromptModal();
    document.getElementById('prompt-modal').classList.add('open');
  });
  document.getElementById('btn-close-prompt-modal').addEventListener('click', () => {
    document.getElementById('prompt-modal').classList.remove('open');
  });
  document.getElementById('prompt-modal').addEventListener('click', e => {
    if (e.target.id === 'prompt-modal') e.target.classList.remove('open');
  });
  document.getElementById('btn-export-audit').addEventListener('click', () => {
    const payload = {
      exported_at: new Date().toISOString(),
      suite: DATA.suite,
      experiment_dir: DATA.experiment_dir,
      human_audit: state.humanAudit,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `trivae-eval-v2-human-audit-${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
  document.getElementById('input-import-audit').addEventListener('change', e => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result || '{}'));
        const imported = parsed.human_audit || parsed;
        if (imported && typeof imported === 'object') {
          state.humanAudit = { ...state.humanAudit, ...imported };
          saveHumanAudit();
          renderSidebar();
          renderCaseDetail();
          alert('已成功导入审核记录！');
        }
      } catch (err) { alert('导入失败：JSON 格式无效。'); }
    };
    reader.readAsText(file);
    e.target.value = '';
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', e => {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) return;
    if (e.key === 'Escape') {
      document.getElementById('prompt-modal').classList.remove('open');
      return;
    }
    const list = filteredCases();
    const curIdx = list.findIndex(x => x.case_id === state.selectedCaseId);
    if ((e.key === 'ArrowDown' || e.key === 'j') && curIdx >= 0 && curIdx < list.length - 1) {
      e.preventDefault();
      state.selectedCaseId = list[curIdx + 1].case_id;
      renderSidebar(); renderCaseDetail();
    } else if ((e.key === 'ArrowUp' || e.key === 'k') && curIdx > 0) {
      e.preventDefault();
      state.selectedCaseId = list[curIdx - 1].case_id;
      renderSidebar(); renderCaseDetail();
    }
  });

  updateAuditProgressBadge();
  renderKpis();
  renderSidebar();
  renderCaseDetail();
})();
</script>
</body>
</html>
"""


def build_html(experiment_dir: Path, output_path: Path) -> dict[str, Any]:
    dataset = collect_audit_dataset(experiment_dir)
    compact_json = json.dumps(dataset, ensure_ascii=False, separators=(",", ":"))
    safe_json = _escape_for_script_tag(compact_json)
    html = HTML_TEMPLATE.replace("__AUDIT_DATA_JSON__", safe_json, 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return {
        "output_path": str(output_path),
        "size_bytes": output_path.stat().st_size,
        "cases": len(dataset["cases"]),
        "runs": len(dataset["cases"]) * 2,
        "judged_v3": sum(
            1
            for c in dataset["cases"]
            for arm in ("baseline", "candidate")
            if c["arms"][arm]["judge_v3"] is not None
        ),
        "judged_v2_1": sum(
            1
            for c in dataset["cases"]
            for arm in ("baseline", "candidate")
            if c["arms"][arm]["judge_v2_1"] is not None
        ),
        "pairwise": sum(1 for c in dataset["cases"] if c["pairwise"] is not None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline HTML audit viewer for eval@v2 A/B runs.")
    parser.add_argument(
        "--experiment-dir",
        type=Path,
        default=DEFAULT_EXPERIMENT_DIR,
        help="Path to the eval-v2-e2e experiment directory (default: data/evaluation/eval-v2-e2e-20261122)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output HTML file path (default: <experiment-dir>/audit-viewer.html)",
    )
    args = parser.parse_args()
    out_path = args.output or (args.experiment_dir / DEFAULT_OUTPUT_FILENAME)
    stats = build_html(args.experiment_dir, out_path)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
