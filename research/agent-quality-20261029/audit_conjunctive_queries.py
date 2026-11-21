"""Saved form of the executed six-query R5 audit; use a new output path to reproduce."""
import argparse
import json
from pathlib import Path

from trivae.capabilities.contracts import ExecutionScope, SearchMessagesInput
from trivae.capabilities.search_messages import SearchMessagesCapability
from trivae.data.storage.sqlite_read import SQLiteCanonicalReadRepository
from trivae.retrieval.lexical import LexicalRetrieval

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/evaluation/agent-quality-codex-20261030"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo = SQLiteCanonicalReadRepository(ROOT / "data/evaluation/frozen-20261028-validated/trivae.sqlite3")
    capability = SearchMessagesCapability(LexicalRetrieval(repo))
    checklist = json.loads((ROOT / "data/evaluation/prompt-ab-eval-v1-20261029/fact-checklist.json").read_text())
    paired = json.loads((OUT / "semantic-rank-candidate.json").read_text())
    corrections = {c["original"]: c["resolved"] for c in paired["gt_corrections"]}
    rows = []
    for cid, terms in [("cap1-08-kimi-deepseek", ["Kimi", "DeepSeek"]), ("cap1-07-mcp-skills", ["MCP", "Skills"])]:
        case = next(c for c in checklist["cases"] if c["case_id"] == cid)
        targets = {corrections.get(mid, mid) for fact in case["criteria"] for mid in fact["evidence"]}
        for query in [*terms, " ".join(terms)]:
            result = capability.execute(SearchMessagesInput(keyword=query, limit=100, context_before=0, context_after=0),
                                        ExecutionScope(max_results=100))
            ids = {m.internal_message_id for m in result.expanded_messages}
            rows.append({"case": cid, "keyword": query, "total_hits": result.total_hits, "returned": len(ids),
                         "gt_ids": sorted(targets & ids), "gt_count": len(targets & ids), "ids": sorted(ids)})
    with args.output.open("x") as stream:
        json.dump({"scope": "same frozen snapshot, lexical limit100, no context, query string only", "rows": rows},
                  stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
