"""Run the production eval CLI with an explicit retention arm and cumulative HTTP meter."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from model_request_meter import install_meter
from replay_semantic_capacity import baseline_class


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--http-record-dir", type=Path, required=True)
    parser.add_argument("--research-state-dir", type=Path, required=True)
    known, remaining = parser.parse_known_args()
    if known.arm == "baseline":
        import trivae.retrieval.semantic.retrieval as retrieval

        retrieval.SemanticRetrieval = baseline_class("003642b3")
    install_meter("agent", known.arm, known.http_record_dir, research=known.research_state_dir)
    from trivae.interfaces.cli import main as cli_main

    return cli_main(remaining)


if __name__ == "__main__":
    sys.exit(main())
