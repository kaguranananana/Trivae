"""Create a private model variant using the fixed eval@v1 conditions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from trivae.config.dotenv import load_environment_file
from trivae.config.settings import load_router_jev_settings, load_settings
from trivae.evaluation.benchmark.environment import _git_commit
from trivae.evaluation.capability_conditions import FORMAL_RUNTIME, FORMAL_TOOLS, validate_formal_conditions
from trivae.evaluation.contracts import EvaluationContractError
from trivae.evaluation.variant import ControlledVariant


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--variant-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    load_environment_file(args.env_file)
    settings = load_settings()
    freeze = json.loads(args.freeze_manifest.read_text(encoding="utf-8"))
    index = freeze["index_state"].get("semantic_index")
    if index is None:
        raise EvaluationContractError("formal suite requires its frozen semantic index")
    variant = ControlledVariant(
        variant_id=args.variant_id, code_version=_git_commit(), provider=settings.provider, model=settings.model_name,
        role="candidate", prompt_identity="production-default", runtime_configuration={"trace_profile": "normal"},
        available_tools=FORMAL_TOOLS, retrieval_configuration={"surface": "agent-facing"},
        index_identity=json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        context_expansion_configuration={"context_window_limit": None},
        evidence_citation_version="production-default", budget=FORMAL_RUNTIME,
    )
    validate_formal_conditions(variant, settings.to_safe_dict(), load_router_jev_settings().to_safe_dict())
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(variant.to_dict(), file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps({"variant_id": variant.variant_id, "provider": variant.provider, "model": variant.model,
                      "code_version": variant.code_version}, ensure_ascii=False))


if __name__ == "__main__":
    main()
