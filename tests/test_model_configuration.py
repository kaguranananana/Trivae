"""Named profiles keep model identity separate from API keys and OAuth state."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trivae.config.models import ModelConfigurationError, load_model_catalog
from trivae.config.settings import SettingsError, load_settings
from trivae.query.runtime.model_completion import complete_json, completion_record


def test_repository_model_catalog_has_independent_query_agent_and_judge_defaults():
    catalog = load_model_catalog()
    assert catalog.select("query").profile_id == "gpt-plus"
    assert catalog.select("agent").profile_id == "deepseek-flash"
    assert catalog.select("judge").profile_id == "gpt-plus"
    assert catalog.select("judge").auth_type == "chatgpt_oauth"
    assert catalog.select("judge").reasoning_effort == "medium"
    assert catalog.select("agent").auth_env == "DEEPSEEK_API_KEY"


def test_named_api_profile_uses_its_secret_env_and_ignores_legacy_model_identity():
    settings = load_settings(
        {
            "DEEPSEEK_API_KEY": "api-key-fixture",
            "TRIVAE_MODEL_PROVIDER": "chatgpt-plan",
            "TRIVAE_MODEL_NAME": "old-chatgpt-profile",
            "TRIVAE_MODEL_API_KEY": "stale-generic-key",
        },
        model_id="deepseek-flash",
    )
    assert (settings.provider, settings.model_name, settings.base_url) == (
        "deepseek",
        "deepseek-flash",
        "https://api.deepseek.com",
    )
    assert settings.api_key == "api-key-fixture"
    safe = settings.to_safe_dict()
    assert safe["model_profile"] == "deepseek-flash"
    assert safe["auth_mode"] == "api_key"
    assert safe["api_key_env"] == "DEEPSEEK_API_KEY"
    assert "api-key-fixture" not in repr(settings)
    assert "api-key-fixture" not in json.dumps(safe)


def test_named_api_profile_requires_the_declared_secret_environment_variable():
    with pytest.raises(SettingsError, match="DEEPSEEK_API_KEY"):
        load_settings({}, model_id="deepseek-flash")


def test_chatgpt_named_profile_keeps_official_oauth_boundary_and_ignores_api_keys():
    settings = load_settings(
        {"DEEPSEEK_API_KEY": "api-key-fixture", "TRIVAE_MODEL_API_KEY": "legacy-key"},
        model_id="gpt-plus",
    )
    assert settings.provider == "chatgpt-plan"
    assert settings.model_name == "gpt-6.1-sol"
    assert settings.base_url == "https://api.openai.com/v1"
    assert settings.api_key == ""
    assert settings.chatgpt_reasoning_effort == "medium"
    assert settings.to_safe_dict()["auth_mode"] == "chatgpt_oauth"


def test_model_catalog_rejects_provider_auth_mismatch(tmp_path: Path):
    config = tmp_path / "models.yaml"
    config.write_text(
        "models:\n  gpt:\n    provider: chatgpt-plan\n    model: gpt-6.1-sol\n"
        "    auth:\n      type: api_key\n      env: OPENAI_API_KEY\n"
        "defaults:\n  query: gpt\nevaluation:\n  agent: gpt\n  judge: gpt\n",
        encoding="utf-8",
    )
    with pytest.raises(ModelConfigurationError, match="chatgpt_oauth"):
        load_model_catalog(config)


def test_api_key_judge_request_uses_selected_model_parameters_and_no_retries():
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"axes":{}}'), finish_reason="stop")],
        model="deepseek-flash",
        usage=SimpleNamespace(model_dump=lambda **_: {"prompt_tokens": 120, "completion_tokens": 60}),
        _request_id="request-fixture",
    )
    client = AsyncMock()
    client.chat.completions.create.return_value = response
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)
    settings = load_settings(
        {"DEEPSEEK_API_KEY": "api-key-fixture", "TRIVAE_MAX_OUTPUT_TOKENS": "16000"},
        model_id="deepseek-flash",
    )
    with patch("trivae.query.runtime.model_completion.AsyncOpenAI", return_value=context) as constructor:
        completion = asyncio.run(
            complete_json(settings, system_prompt="score", user_prompt="payload", session_id="run-1")
        )
    assert constructor.call_args.kwargs["api_key"] == "api-key-fixture"
    assert constructor.call_args.kwargs["max_retries"] == 0
    request = client.chat.completions.create.call_args.kwargs
    assert request["model"] == "deepseek-flash"
    assert request["messages"] == [
        {"role": "system", "content": "score"},
        {"role": "user", "content": "payload"},
    ]
    assert request["temperature"] == 0
    assert request["max_tokens"] == 16000
    assert request["reasoning_effort"] == "low"
    assert request["response_format"] == {"type": "json_object"}
    assert completion.finish_reason == "stop"
    assert completion.usage == {"prompt_tokens": 120, "completion_tokens": 60}
    assert "api-key-fixture" not in json.dumps(completion_record(completion))


def test_chatgpt_judge_uses_existing_oauth_responses_model_without_api_client():
    settings = load_settings({"DEEPSEEK_API_KEY": "api-key-fixture"}, model_id="gpt-plus")
    auth = object()
    model = MagicMock()
    model.request_projection.return_value = {
        "provider": "chatgpt-plan",
        "model": "gpt-6.1-sol",
        "endpoint": "https://api.openai.com/v1/responses",
        "store": False,
        "stream": True,
        "reasoning": {"summary": "auto", "effort": "medium"},
    }
    model._payload.return_value = {"model": "gpt-6.1-sol", "input": []}
    model.collect_response = AsyncMock(
        return_value=(
            SimpleNamespace(
                output_text='{"axes":{}}',
                model="gpt-6.1-sol",
                id="response-fixture",
                status="completed",
                usage=None,
            ),
            {"status_code": 200, "request_id": "request-fixture", "stream_completed": True},
        )
    )
    model.close = AsyncMock()
    with (
        patch("trivae.query.runtime.model_completion.ChatGPTAuthManager", return_value=auth),
        patch("trivae.query.runtime.model_completion.ChatGPTResponsesModel", return_value=model) as constructor,
        patch("trivae.query.runtime.model_completion.AsyncOpenAI") as api_client,
    ):
        completion = asyncio.run(
            complete_json(settings, system_prompt="judge prompt", user_prompt="case", session_id="run-2")
        )
    constructor.assert_called_once_with(model="gpt-6.1-sol", auth=auth, reasoning_effort="medium")
    model._payload.assert_called_once()
    assert model._payload.call_args.args[0] == "judge prompt"
    assert model._payload.call_args.args[1] == [{"role": "user", "content": "case"}]
    model.close.assert_awaited_once()
    api_client.assert_not_called()
    assert completion.finish_reason == "completed"
    assert completion.request["endpoint"] == "https://api.openai.com/v1/responses"
    assert completion.request["reasoning"] == {"summary": "auto", "effort": "medium"}
    assert completion.request_id == "request-fixture"
