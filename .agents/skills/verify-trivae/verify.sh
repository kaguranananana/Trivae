#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../../.."
mkdir -p data/evaluation/verify-trivae
evidence=$(mktemp -d "$PWD/data/evaluation/verify-trivae/run.XXXXXX")
echo "Evidence: $evidence"

scratch=$(mktemp -d "${TMPDIR:-/tmp}/trivae-verify.XXXXXX")
cleanup() {
    rm -rf -- "$scratch"
    echo "Removed scratch: $scratch"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export TMPDIR="$scratch"

uv_run=(uv run --offline --no-sync --no-env-file)

run_logged() {
    local log=$1 status=0
    shift
    {
        printf '%q ' "$@"
        printf '\n'
        "$@" || status=$?
        printf 'Exit: %s\n' "$status"
        return "$status"
    } 2>&1 | tee "$evidence/$log"
}

run_logged doctor.log "${uv_run[@]}" trivae --help

# eval 还有自己的 dotenv 加载器，显式给它本次运行的空文件。
touch "$scratch/verify.env"
run_logged cases.log "${uv_run[@]}" trivae eval --env-file "$scratch/verify.env" cases validate evaluation/cases

run_logged pytest.log "${uv_run[@]}" pytest -v -p no:cacheprovider \
    --basetemp "$scratch/pytest" --junitxml "$evidence/pytest.xml" \
    tests/test_lexical_retrieval.py::LexicalRetrievalTests::test_fts5_rebuild_and_session_scoped_bounded_hits \
    tests/test_lexical_retrieval.py::LexicalRetrievalTests::test_new_canonical_message_requires_explicit_rebuild \
    tests/test_chinese_lexical_regression.py::ChineseLexicalRetrievalTests::test_chinese_substring_query_hits_all_containing_messages \
    tests/test_semantic_retrieval.py::SemanticRetrievalTests::test_application_builds_independent_semantic_index_and_recovers_canonical_messages \
    tests/test_import_index_updates.py::test_real_updater_makes_new_native_and_forwarded_messages_available_to_agent \
    tests/test_context_source_contract.py \
    tests/test_reply_context.py \
    tests/test_evidence.py::GracefulFinalizationTests::test_one_invalid_citation_is_dropped_while_valid_citation_survives \
    tests/test_evidence.py::GracefulFinalizationTests::test_all_invalid_citations_keep_answer_but_do_not_look_grounded \
    tests/test_evidence.py::ProvenanceValidationTests::test_fabricated_run_tool_result_item_and_old_run_fail \
    tests/test_evidence.py::ProvenanceValidationTests::test_source_outside_execution_scope_fails_even_if_context_was_returned \
    tests/test_evaluation.py::EvaluationRunnerTests::test_invalid_citation_is_a_hard_deterministic_failure \
    tests/test_evaluation.py::EvaluationRunnerTests::test_degraded_artifact_is_deliverable_but_not_grounded_pass \
    tests/test_evaluation.py::EvaluationRunnerTests::test_runner_exception_is_persisted_and_re_raised \
    tests/test_evaluation.py::ApplicationEvaluationTests::test_forced_standard_bypasses_router_and_trace_keeps_override \
    tests/test_web_server.py::WebApiTests::test_readiness_and_source_sessions \
    tests/test_web_server.py::WebApiTests::test_stream_query_completes_with_sources_and_end \
    tests/test_web_server.py::WebApiTests::test_stream_follow_up_reuses_conversation_and_rejects_scope_change
