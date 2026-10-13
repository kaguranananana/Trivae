"""官方 OAuth 契约回归：本地签名 ID token，HTTP mock 不读取真实凭证。"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from cryptography.hazmat.primitives.asymmetric import rsa

from trivae.auth import ChatGPTAuthError, ChatGPTAuthManager, ChatGPTAuthStore
from trivae.auth.chatgpt import DISCOVERY_URL, ISSUER, RESOURCE, SCOPES, TOKEN_URL


class OAuthServer:
    """Mock 官方服务器及浏览器回调，仍通过真实 loopback socket 接收 code。"""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwk.update(kid="local-test", alg="RS256", use="sig")
        self.subject = "verified-user"
        self.client_id = "oaiapp_test"
        self.scopes: str | None = SCOPES
        self.auth_params: dict[str, str] = {}
        self.form_requests: list[dict[str, str]] = []
        self.browser_tasks: list[asyncio.Task[None]] = []
        self.callback_changes: dict[str, str | None] = {}
        self.claim_changes: dict[str, object] = {}
        self.refresh_payload: dict[str, object] | None = None
        self.token_error: tuple[int, dict[str, object]] | None = None
        self.revoke_status = 200

    def token(self) -> str:
        claims = {
            "iss": ISSUER,
            "aud": self.client_id,
            "sub": self.subject,
            "exp": time.time() + 3600,
            "nonce": self.auth_params["nonce"],
            "email": "same@example.com",
        }
        claims.update(self.claim_changes)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "local-test"})

    def handle(self, request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
                    "revocation_endpoint": f"{ISSUER}/api/accounts/oauth/revoke",
                },
            )
        if request.url.path == "/.well-known/jwks.json":
            return httpx.Response(200, json={"keys": [self.jwk]})
        if str(request.url) == TOKEN_URL:
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            self.form_requests.append(form)
            if self.token_error:
                return httpx.Response(
                    self.token_error[0], json=self.token_error[1], headers={"x-request-id": "req-auth"}
                )
            if form["grant_type"] == "refresh_token":
                return httpx.Response(
                    200,
                    json=self.refresh_payload
                    or {
                        "access_token": "new-access",
                        "refresh_token": "rotated-refresh",
                        "token_type": "Bearer",
                        "expires_in": 3600,
                    },
                )
            assert form["client_id"] == self.client_id
            assert form["redirect_uri"] == self.auth_params["redirect_uri"]
            assert form["resource"] == RESOURCE
            assert create_s256_code_challenge(form["code_verifier"]) == self.auth_params["code_challenge"]
            payload = {
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
                "id_token": self.token(),
                "token_type": "Bearer",
                "expires_in": 3600,
            }
            if self.scopes is not None:
                payload["scope"] = self.scopes
            return httpx.Response(200, json=payload)
        if request.url.path == "/api/accounts/oauth/revoke":
            self.form_requests.append({key: value[0] for key, value in parse_qs(request.content.decode()).items()})
            return httpx.Response(
                self.revoke_status, text="" if self.revoke_status == 200 else "revocation unavailable"
            )
        if str(request.url) == f"{RESOURCE}/models":
            assert request.headers["authorization"] in {"Bearer secret-access", "Bearer new-access"}
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"slug": "account-only-model", "display_name": "Allowed GPT", "visibility": "list"},
                        {"slug": "internal", "display_name": "Hidden", "visibility": "hidden"},
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    def browser(self, url: str) -> bool:
        self.auth_params = {key: values[0] for key, values in parse_qs(urlsplit(url).query).items()}

        async def complete() -> None:
            params = {"state": self.auth_params["state"], "code": "code-secret", "client_id": self.client_id}
            for key, value in self.callback_changes.items():
                if value is None:
                    params.pop(key, None)
                else:
                    params[key] = value
            async with httpx.AsyncClient(trust_env=False) as browser:
                await browser.get(f"{self.auth_params['redirect_uri']}?{urlencode(params)}")

        self.browser_tasks.append(asyncio.create_task(complete()))
        return True


def run(coroutine: object) -> object:
    """测试统一使用 asyncio.run，不依赖额外 pytest 插件。"""
    return asyncio.run(coroutine)  # type: ignore[arg-type]


def setup(tmp_path: Path) -> tuple[ChatGPTAuthStore, OAuthServer, ChatGPTAuthManager]:
    store = ChatGPTAuthStore(tmp_path / "private")
    server = OAuthServer()
    client = httpx.AsyncClient(transport=httpx.MockTransport(server.handle))
    return store, server, ChatGPTAuthManager(store, client=client)


def test_first_login_pkce_identity_storage_models_and_safe_metadata(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        metadata = await manager.login(browser_opener=server.browser)
        assert metadata["account_id"] == "oaiapp_test"
        assert server.auth_params["client_id"] == "dynamic_agent_client"
        assert server.auth_params["agent_name_hint"] == "Trivae"
        assert server.auth_params["code_challenge_method"] == "S256"
        assert urlsplit(server.auth_params["redirect_uri"]).hostname == "127.0.0.1"
        assert await manager.access_token() == "secret-access"
        assert await manager.list_models() == [{"slug": "account-only-model", "display_name": "Allowed GPT"}]
        await asyncio.gather(*server.browser_tasks)

    run(scenario())
    assert store.directory.stat().st_mode & 0o777 == 0o700
    assert store.path.stat().st_mode & 0o777 == 0o600
    safe = json.dumps(store.status())
    assert "secret-access" not in safe and "secret-refresh" not in safe
    assert store.status()["authenticated"] and store.status()["plan_usage_enabled"]
    with store.locked():
        assert "secret-access" not in repr(store._credential(store._read()))


def test_reauthorization_reuses_client_host_and_identity_hints(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        host_id = server.auth_params["ext_agent_host_id"]
        old_nonce = server.auth_params["nonce"]
        server.callback_changes["client_id"] = None
        await manager.login(browser_opener=server.browser)
        assert server.auth_params["client_id"] == server.client_id
        assert server.auth_params["ext_agent_host_id"] == host_id
        assert server.auth_params["nonce"] != old_nonce
        assert "agent_name_hint" not in server.auth_params
        assert server.auth_params["id_token_hint"]
        assert server.auth_params["login_hint"] == "same@example.com"
        await asyncio.gather(*server.browser_tasks)

    run(scenario())
    assert len(store.status()["accounts"]) == 1


@pytest.mark.parametrize(
    "change,code",
    [
        ({"state": "wrong"}, "AUTH_STATE"),
        ({"client_id": None}, "AUTH_CLIENT"),
        ({"client_id": "dynamic_agent_client"}, "AUTH_CLIENT"),
        ({"error": "access_denied", "code": None}, "AUTH_DENIED"),
    ],
)
def test_callback_failure_never_exchanges_or_saves_credentials(
    tmp_path: Path, change: dict[str, str | None], code: str
) -> None:
    store, server, manager = setup(tmp_path)
    server.callback_changes = change

    async def scenario() -> None:
        with pytest.raises(ChatGPTAuthError, match=code):
            await manager.login(browser_opener=server.browser)
        await asyncio.gather(*server.browser_tasks)

    run(scenario())
    assert server.form_requests == []
    assert store.status()["accounts"] == []


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other.example"},
        {"aud": "other-client"},
        {"exp": time.time() - 60},
        {"nonce": "wrong-nonce"},
        {"sub": ""},
    ],
)
def test_oidc_rejects_invalid_claims(tmp_path: Path, claims: dict[str, object]) -> None:
    store, server, manager = setup(tmp_path)
    server.claim_changes = claims

    async def scenario() -> None:
        with pytest.raises(ChatGPTAuthError, match="AUTH_OIDC"):
            await manager.login(browser_opener=server.browser)
        await asyncio.gather(*server.browser_tasks)

    run(scenario())
    assert store.status()["accounts"] == []


@pytest.mark.parametrize("mismatch", ["client", "subject"])
def test_relogin_mismatch_preserves_selected_registration(tmp_path: Path, mismatch: str) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        before = store.path.read_bytes()
        if mismatch == "client":
            server.callback_changes["client_id"] = "oaiapp_other"
        else:
            server.subject = "another-user"
        with pytest.raises(ChatGPTAuthError, match="AUTH_CLIENT|AUTH_IDENTITY"):
            await manager.login(browser_opener=server.browser)
        assert store.path.read_bytes() == before
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_same_email_and_subject_registrations_are_separate(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        server.client_id = "oaiapp_second_workspace"
        await manager.login(new_account=True, browser_opener=server.browser)
        await asyncio.gather(*server.browser_tasks)

    run(scenario())
    assert len(store.status()["accounts"]) == 2
    assert store.status()["selected_account"] == "oaiapp_second_workspace"
    store.select_account("oaiapp_test")
    assert store.status()["selected_account"] == "oaiapp_test"


def test_running_manager_pins_account_across_external_selection(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        assert manager.account_id == "oaiapp_test"
        # 第二个 manager 模拟另一个 CLI 进程注册账号 B，然后把 active 切到 B。
        other = ChatGPTAuthManager(store, client=httpx.AsyncClient(transport=httpx.MockTransport(server.handle)))
        server.client_id = "oaiapp_second_workspace"
        await other.login(new_account=True, browser_opener=server.browser)
        assert other.account_id == "oaiapp_second_workspace"
        assert store.status()["selected_account"] == "oaiapp_second_workspace"
        # 给 B 单独设置 token，以证实已运行的 A manager 没有读取 B 的凭证。
        with store.locked():
            data = store._read()
            data["accounts"]["oaiapp_second_workspace"]["access_token"] = "account-b-token"
            store._write(data)
        assert await manager.access_token() == "secret-access"
        assert await manager.list_models() == [{"slug": "account-only-model", "display_name": "Allowed GPT"}]
        fresh = ChatGPTAuthManager(store, client=httpx.AsyncClient(transport=httpx.MockTransport(server.handle)))
        assert await fresh.access_token() == "account-b-token"
        assert fresh.account_id == "oaiapp_second_workspace"
        store.select_account("oaiapp_test")
        assert await fresh.access_token() == "account-b-token"
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


@pytest.mark.parametrize("scope", [None, "openid profile email"])
def test_identity_only_grant_saved_but_inference_prohibited(tmp_path: Path, scope: str | None) -> None:
    store, server, manager = setup(tmp_path)
    server.scopes = scope

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        with pytest.raises(ChatGPTAuthError, match="AUTH_SCOPE"):
            await manager.access_token()
        await asyncio.gather(*server.browser_tasks)

    run(scenario())
    assert store.status()["authenticated"]
    assert not store.status()["plan_usage_enabled"]


def expire(store: ChatGPTAuthStore) -> None:
    with store.locked():
        data = store._read()
        data["accounts"][data["selected_account"]]["expires_at"] = time.time() - 1
        store._write(data)


def test_refresh_rotation_preserves_scopes_and_serializes_managers(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        second = ChatGPTAuthManager(store, client=httpx.AsyncClient(transport=httpx.MockTransport(server.handle)))
        assert await asyncio.gather(manager.access_token(), second.access_token()) == ["new-access", "new-access"]
        refreshes = [form for form in server.form_requests if form.get("grant_type") == "refresh_token"]
        assert len(refreshes) == 1
        assert "scope" not in refreshes[0]
        assert refreshes[0]["client_id"] == server.client_id
        assert refreshes[0]["refresh_token"] == "secret-refresh"
        with store.locked():
            credential = store._credential(store._read())
        assert credential.refresh_token == "rotated-refresh"
        assert set(credential.scopes) == set(SCOPES.split())
        expire(store)
        await second.access_token()
        assert server.form_requests[-1]["refresh_token"] == "rotated-refresh"
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_refresh_revocation_error_retains_safe_root_cause(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        server.token_error = (400, {"error": "invalid_grant", "error_description": "revoked secret-refresh"})
        with pytest.raises(ChatGPTAuthError) as error:
            await manager.access_token()
        assert "invalid_grant" in str(error.value)
        assert "req-auth" in str(error.value)
        assert "secret-refresh" not in str(error.value)
        assert error.value.oauth_code == "invalid_grant"
        assert error.value.status_code == 400
        assert error.value.request_id == "req-auth"
        assert not store.status()["authenticated"]
        assert len(store.status()["accounts"]) == 1
        assert "secret-refresh" not in store.path.read_text()
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_pending_issued_client_reused_after_failed_first_code_exchange(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        server.token_error = (400, {"error": "invalid_grant", "error_description": "expired authorization code"})
        with pytest.raises(ChatGPTAuthError, match="invalid_grant"):
            await manager.login(browser_opener=server.browser)
        assert store.status()["accounts"] == []
        assert store.status()["pending_registrations"] == [server.client_id]
        assert not store.status()["authenticated"]
        server.token_error = None
        server.callback_changes["client_id"] = None
        await manager.login(browser_opener=server.browser)
        assert server.auth_params["client_id"] == server.client_id
        assert "agent_name_hint" not in server.auth_params
        assert store.status()["pending_registrations"] == []
        assert store.status()["authenticated"]
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


@pytest.mark.parametrize(
    "code",
    [
        "invalid_refresh_token",
        "token_expired",
        "refresh_token_expired",
        "refresh_token_invalidated",
        "refresh_token_reused",
    ],
)
def test_terminal_refresh_errors_clear_tokens(tmp_path: Path, code: str) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        server.token_error = (400, {"error": {"code": code, "message": "session cannot renew"}})
        with pytest.raises(ChatGPTAuthError) as error:
            await manager.access_token()
        assert error.value.oauth_code == code
        assert not store.status()["authenticated"]
        assert store.status()["selected_account"] == server.client_id
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_temporary_refresh_error_preserves_credential_record(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        before = store.path.read_bytes()
        server.token_error = (503, {"detail": "temporary outage"})
        with pytest.raises(ChatGPTAuthError, match="temporary outage"):
            await manager.access_token()
        assert store.path.read_bytes() == before
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_refresh_requires_replacement_refresh_token(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        before = store.path.read_bytes()
        server.refresh_payload = {"access_token": "new-access", "token_type": "Bearer", "expires_in": 3600}
        with pytest.raises(ChatGPTAuthError, match="replacement refresh token"):
            await manager.access_token()
        assert store.path.read_bytes() == before
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


@pytest.mark.parametrize(
    "change",
    [
        {"token_type": None},
        {"access_token": []},
        {"refresh_token": []},
        {"scope": []},
    ],
)
def test_malformed_token_response_is_explicit_and_does_not_replace_credentials(
    tmp_path: Path, change: dict[str, object]
) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        before = store.path.read_bytes()
        server.refresh_payload = {
            "access_token": "new-access",
            "refresh_token": "rotated-refresh",
            "token_type": "Bearer",
            "expires_in": 3600,
            **change,
        }
        with pytest.raises(ChatGPTAuthError, match="AUTH_RESPONSE"):
            await manager.access_token()
        assert store.path.read_bytes() == before
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_readiness_status_returns_during_refresh_network_wait(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        started, release = asyncio.Event(), asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == TOKEN_URL:
                started.set()
                await release.wait()
            return server.handle(request)

        manager._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        refresh = asyncio.create_task(manager.access_token())
        await asyncio.wait_for(started.wait(), 2)
        # 同 event loop 的同步 status 必须直接读原子快照，不能等待刷新持有的锁。
        try:
            status = store.status()
            assert status["authenticated"]
        finally:
            release.set()
        assert await refresh == "new-access"
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_identity_only_reauthorization_explicitly_requests_consent(tmp_path: Path) -> None:
    _, server, manager = setup(tmp_path)

    async def scenario() -> None:
        server.scopes = "openid email profile"
        await manager.login(browser_opener=server.browser)
        server.scopes = SCOPES
        await manager.login(browser_opener=server.browser)
        assert server.auth_params["prompt"] == "consent"
        await manager.login(browser_opener=server.browser)
        assert "prompt" not in server.auth_params
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_oidc_signature_rejects_an_untrusted_signing_key(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)
    # JWKS 保持原来的公钥，token 则用不被该 JWKS 信任的另一私钥签名。
    server.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    async def scenario() -> None:
        with pytest.raises(ChatGPTAuthError, match="Signature verification failed"):
            await manager.login(browser_opener=server.browser)
        assert not store.status()["authenticated"]
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


@pytest.mark.parametrize("status", [200, 503])
def test_logout_clears_tokens_preserves_host_and_registration(tmp_path: Path, status: int) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        host_id = store.host_id()
        server.revoke_status = status
        if status == 200:
            await manager.logout()
        else:
            with pytest.raises(ChatGPTAuthError, match="remote revocation unconfirmed"):
                await manager.logout()
        assert store.host_id() == host_id
        assert store.status()["selected_account"] == "oaiapp_test"
        assert not store.status()["authenticated"]
        raw = store.path.read_text()
        assert "secret-access" not in raw and "secret-refresh" not in raw
        assert server.form_requests[-1] == {
            "token": "secret-refresh",
            "token_type_hint": "refresh_token",
            "client_id": server.client_id,
        }
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_redaction_hides_bearer_secrets_and_whole_authorization_url(tmp_path: Path) -> None:
    _, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        message = manager.redact(
            "network error: Bearer secret-access; refresh_token=secret-refresh "
            "https://auth.openai.com/api/accounts/authorize?id_token_hint=retained-secret&state=opaque"
        )
        assert "network error" in message
        for secret in ("secret-access", "secret-refresh", "retained-secret", "opaque"):
            assert secret not in message
        await asyncio.gather(*server.browser_tasks)

    run(scenario())


def test_timeout_and_browser_failure_are_explicit(tmp_path: Path) -> None:
    _, _, manager = setup(tmp_path)

    async def scenario() -> None:
        with pytest.raises(ChatGPTAuthError, match="AUTH_TIMEOUT"):
            await manager.login(browser_opener=lambda _: True, timeout_seconds=0.01)
        with pytest.raises(ChatGPTAuthError, match="AUTH_BROWSER"):
            await manager.login(browser_opener=lambda _: False)

    run(scenario())


def test_storage_refuses_repository_and_readable_credentials(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(ChatGPTAuthError, match="outside a Git repository"):
        ChatGPTAuthStore(tmp_path / "auth")
    (tmp_path / ".git").rmdir()
    store = ChatGPTAuthStore(tmp_path / "private")
    store.host_id()
    os.chmod(store.path, 0o644)
    with pytest.raises(ChatGPTAuthError, match="0600"):
        store.status()


def _process_lock(directory: str, ready: object, release: object) -> None:
    """子进程持有真实文件锁，用于证明刷新等候其它进程释放。"""
    store = ChatGPTAuthStore(Path(directory))
    with store.locked():
        ready.set()  # type: ignore[attr-defined]
        release.wait(5)  # type: ignore[attr-defined]


def test_refresh_waits_for_cross_process_lock(tmp_path: Path) -> None:
    store, server, manager = setup(tmp_path)

    async def scenario() -> None:
        await manager.login(browser_opener=server.browser)
        expire(store)
        context = multiprocessing.get_context("spawn")
        ready, release = context.Event(), context.Event()
        process = context.Process(target=_process_lock, args=(str(store.directory), ready, release))
        process.start()
        try:
            assert await asyncio.to_thread(ready.wait, 5)
            refresh = asyncio.create_task(manager.access_token())
            await asyncio.sleep(0.1)
            assert not refresh.done()
            assert not any(form.get("grant_type") == "refresh_token" for form in server.form_requests)
            release.set()
            assert await refresh == "new-access"
        finally:
            release.set()
            await asyncio.to_thread(process.join, 5)
            if process.is_alive():
                process.terminate()
        assert process.exitcode == 0
        await asyncio.gather(*server.browser_tasks)

    run(scenario())
