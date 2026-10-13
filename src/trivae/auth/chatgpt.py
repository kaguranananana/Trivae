"""官方 ChatGPT plan OAuth、账号注册与受保护凭证存储。"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import re
import secrets
import tempfile
import time
import uuid
import webbrowser
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt

# Authlib 尚未发布 py.typed；此处仅使用其标准 PKCE S256 实现。
from authlib.oauth2.rfc7636 import create_s256_code_challenge  # type: ignore[import-untyped]

ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = f"{ISSUER}/api/accounts/authorize"
TOKEN_URL = f"{ISSUER}/api/accounts/oauth/token"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"
TERMINAL_REFRESH_ERRORS = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}


class ChatGPTAuthError(RuntimeError):
    """显式认证错误；message 只包含脱敏后的诊断。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        oauth_code: str | None = None,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        self.code = code
        self.oauth_code = oauth_code
        self.status_code = status_code
        self.request_id = request_id
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True, repr=False)
class _Credential:
    """禁止默认 repr 输出令牌；安全状态由 metadata 单独投影。"""

    client_id: str
    subject: str
    email: str
    issuer: str
    access_token: str
    refresh_token: str
    id_token: str
    scopes: tuple[str, ...]
    expires_at: float
    token_type: str = "Bearer"

    def metadata(self) -> dict[str, object]:
        """返回可展示的注册信息，不暴露任何凭证。"""
        signed_in = bool(self.access_token and (self.expires_at > time.time() or self.refresh_token))
        return {
            "account_id": self.client_id,
            "client_id": self.client_id,
            "subject": self.subject,
            "email": self.email,
            "label": f"{self.email or self.subject} ({self.client_id})",
            "signed_in": signed_in,
            "expires_at": self.expires_at,
            "scopes": list(self.scopes),
            "plan_usage_enabled": signed_in and {DIRECT_SCOPE, "resource.invoke"}.issubset(self.scopes),
        }


class ChatGPTAuthStore:
    """仓库外、0700 目录、0600 原子文件；同一文件锁串行化所有写入。"""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = (directory or Path.home() / ".config" / "trivae" / "chatgpt").resolve()
        # 凭证位置是显式边界：包括 Git worktree 在内的仓库都不允许存储令牌。
        if any((parent / ".git").exists() for parent in (self.directory, *self.directory.parents)):
            raise ChatGPTAuthError("AUTH_STORAGE", "Credential directory must be outside a Git repository")
        self.path = self.directory / "credentials.json"
        self.lock_path = self.directory / "credentials.lock"

    def _prepare(self) -> None:
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.directory.stat().st_mode & 0o077:
            raise ChatGPTAuthError("AUTH_STORAGE", "Credential directory requires owner-only permissions (0700)")

    def _lock_fd(self) -> int:
        self._prepare()
        return os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o600)

    @contextmanager
    def locked(self) -> Iterator[None]:
        """短本地操作使用阻塞锁，锁文件从不删除，防止不同 inode 分裂锁。"""
        fd = self._lock_fd()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    @asynccontextmanager
    async def async_locked(self) -> AsyncIterator[None]:
        """刷新等待锁时让出 event loop；取消后 finally 关闭 fd 释放锁。"""
        fd = self._lock_fd()
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    # 这里只等待本地互斥锁，不重试 OAuth 或推理请求。
                    await asyncio.sleep(0.05)
            yield
        finally:
            os.close(fd)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "ext_agent_host_id": f"urn:uuid:{uuid.uuid4()}",
                "selected_account": None,
                "accounts": {},
                "pending_registrations": [],
            }
        if self.path.stat().st_mode & 0o077:
            raise ChatGPTAuthError("AUTH_STORAGE", "Credential file requires owner-only permissions (0600)")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not isinstance(value.get("accounts"), dict):
                raise ValueError("expected account records")
            if not isinstance(value.get("ext_agent_host_id"), str) or not value["ext_agent_host_id"]:
                raise ValueError("missing host identity")
            return value
        except (ValueError, OSError) as exc:
            # JSON 内容可能包含令牌，不将原始文档附到诊断里。
            raise ChatGPTAuthError("AUTH_STORAGE", f"Cannot read credential records: {exc}") from None

    def _write(self, data: Mapping[str, Any]) -> None:
        # mkstemp 在替换前已经是 0600，避免先创建可读文件再 chmod 的时间窗口。
        fd, name = tempfile.mkstemp(prefix=".credentials-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _credential(data: Mapping[str, Any], account_id: str | None = None) -> _Credential:
        selected = account_id or data.get("selected_account")
        record = data["accounts"].get(selected)
        if record is None:
            raise ChatGPTAuthError("AUTH_REQUIRED", "Sign in with ChatGPT first or select a saved account")
        try:
            return _Credential(**{**record, "scopes": tuple(record["scopes"])})
        except (KeyError, TypeError) as exc:
            raise ChatGPTAuthError("AUTH_STORAGE", f"Invalid credential record: {type(exc).__name__}") from None

    def host_id(self) -> str:
        """首次授权之前持久化主机 ID；退出登录不会删除它。"""
        with self.locked():
            data = self._read()
            self._write(data)
            return str(data["ext_agent_host_id"])

    def select_account(self, account_id: str) -> None:
        """只按签发 client ID 选择注册，邮箱和 subject 不作为工作区键。"""
        with self.locked():
            data = self._read()
            self._credential(data, account_id)
            data["selected_account"] = account_id
            self._write(data)

    def status(self) -> dict[str, object]:
        """本地状态检查不联网，也不刷新令牌。"""
        # 文件原子替换保证读取完整快照；读状态不等待持锁中的网络刷新，避免同 event loop 死锁。
        data = self._read()
        accounts = [self._credential(data, key).metadata() for key in data["accounts"]]
        selected = next((item for item in accounts if item["account_id"] == data["selected_account"]), None)
        return {
            "provider": "chatgpt-plan",
            "selected_account": data["selected_account"],
            "accounts": accounts,
            "authenticated": bool(selected and selected["signed_in"]),
            "plan_usage_enabled": bool(selected and selected["plan_usage_enabled"]),
            "pending_registrations": list(data.get("pending_registrations", [])),
        }


class ChatGPTAuthManager:
    """认证层独占令牌；Runtime 只通过 access_token 获取本次 Bearer。"""

    def __init__(
        self,
        store: ChatGPTAuthStore | None = None,
        account_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.store = store or ChatGPTAuthStore()
        self.account_id = account_id
        self._client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=False)
        self._owns_client = client is None
        self._secrets: set[str] = set()

    def _remember(self, credential: _Credential) -> None:
        self._secrets.update(
            item for item in (credential.access_token, credential.refresh_token, credential.id_token) if item
        )

    def redact(self, message: str) -> str:
        """诊断保留错误原因，但删除 Bearer、授权 URL 与已知会话秘密。"""
        result = re.sub(
            r"https://auth\.openai\.com/api/accounts/authorize\?[^\s\"']+", "[redacted authorization URL]", message
        )
        result = re.sub(r"(?i)Bearer\s+[^\s\"',;]+", "Bearer [redacted]", result)
        result = re.sub(
            r"(?i)((?:access_token|refresh_token|id_token|code_verifier|id_token_hint)[\"']?\s*[:=]\s*[\"']?)[^\s\"'&,}]+",
            r"\1[redacted]",
            result,
        )
        for secret in sorted(self._secrets, key=len, reverse=True):
            result = result.replace(secret, "[redacted]")
        return result

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            # 连接失败尚无 HTTP 状态；保留失败端点、异常类型和底层消息定位阶段。
            raise ChatGPTAuthError("AUTH_NETWORK", self.redact(f"{method} {url}: {type(exc).__name__}: {exc}")) from None
        if not response.is_success:
            oauth_code = None
            # 服务端可能在诊断中回显 token；先收集已知字段再投影错误。
            try:
                payload = response.json()
                self._remember_payload(payload)
                error = payload.get("error", payload)
                if isinstance(error, str):
                    oauth_code = error
                elif isinstance(error, dict) and isinstance(error.get("code"), str):
                    oauth_code = error["code"]
                detail = json.dumps(payload, ensure_ascii=False)
            except (ValueError, AttributeError):
                detail = response.text
            request_id = response.headers.get("x-request-id", "unknown")
            raise ChatGPTAuthError(
                "AUTH_HTTP",
                self.redact(f"HTTP {response.status_code}, request_id={request_id}: {detail}"),
                oauth_code=oauth_code,
                status_code=response.status_code,
                request_id=request_id,
            )
        return response

    def _remember_payload(self, payload: Any) -> None:
        if isinstance(payload, dict):
            self._secrets.update(
                value
                for key, value in payload.items()
                if key in {"access_token", "refresh_token", "id_token"} and isinstance(value, str) and value
            )

    def _json(self, response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("expected JSON object")
            self._remember_payload(payload)
            return payload
        except ValueError as exc:
            raise ChatGPTAuthError("AUTH_RESPONSE", self.redact(f"Invalid JSON response: {exc}")) from None

    async def _discovery(self) -> dict[str, Any]:
        document = self._json(await self._request("GET", DISCOVERY_URL))
        if document.get("issuer") != ISSUER:
            raise ChatGPTAuthError("AUTH_OIDC", "Discovery issuer does not match OpenAI")
        # discovery 只允许官方 HTTPS endpoint，令牌不跟随重定向到其它主机。
        for key in ("jwks_uri", "revocation_endpoint"):
            endpoint = urlsplit(str(document.get(key, "")))
            if endpoint.scheme != "https" or endpoint.netloc != "auth.openai.com":
                raise ChatGPTAuthError("AUTH_OIDC", f"Discovery {key} is not an official OpenAI endpoint")
        return document

    async def _identity(self, token: str, client_id: str, nonce: str | None) -> dict[str, Any]:
        discovery = await self._discovery()
        jwks = self._json(await self._request("GET", str(discovery["jwks_uri"])))
        try:
            header = jwt.get_unverified_header(token)
            # 仅采用已核对的官方签名算法；不能由 token 自己决定信任算法。
            if header.get("alg") != "RS256":
                raise jwt.InvalidTokenError("ID token requires RS256")
            keys = jwt.PyJWKSet.from_dict(jwks).keys
            signing_key = next((key.key for key in keys if key.key_id == header.get("kid")), None)
            if signing_key is None:
                raise jwt.InvalidTokenError("ID token signing key is absent from OpenAI JWKS")
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=ISSUER,
                options={"require": ["iss", "aud", "exp", "sub"]},
            )
            if not isinstance(claims["sub"], str) or not claims["sub"]:
                raise jwt.InvalidTokenError("ID token subject is missing")
            if nonce is not None and claims.get("nonce") != nonce:
                raise jwt.InvalidTokenError("ID token nonce does not match authorization attempt")
            if isinstance(claims["aud"], list) and len(claims["aud"]) > 1 and claims.get("azp") != client_id:
                raise jwt.InvalidTokenError("ID token authorized party does not match client")
            return claims
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise ChatGPTAuthError("AUTH_OIDC", self.redact(f"ID token validation failed: {exc}")) from None

    async def _tokens(
        self, payload: dict[str, Any], client_id: str, nonce: str | None, previous: _Credential | None
    ) -> _Credential:
        self._remember_payload(payload)
        refresh_token = payload.get("refresh_token", "")
        if not isinstance(refresh_token, str):
            raise ChatGPTAuthError("AUTH_RESPONSE", "Refresh token must be a string")
        if previous and nonce is None and not refresh_token:
            # 官方刷新成功必须返回 replacement；缺失时不能静默复用已轮换的旧令牌。
            raise ChatGPTAuthError("AUTH_RESPONSE", "Refresh response did not include a replacement refresh token")
        token = payload.get("id_token")
        if token is not None and not isinstance(token, str):
            raise ChatGPTAuthError("AUTH_OIDC", "ID token must be a string")
        if nonce is not None and not token:
            raise ChatGPTAuthError("AUTH_OIDC", "Authorization response did not include an ID token")
        if token:
            claims = await self._identity(str(token), client_id, nonce)
            if previous and claims["sub"] != previous.subject:
                raise ChatGPTAuthError("AUTH_IDENTITY", "Verified account identity differs from selected registration")
            subject = claims["sub"]
            email = str(claims.get("email", ""))
        elif previous:
            # 标准 refresh grant 可以不返回 ID token，继续使用已验证的注册身份。
            subject, email = previous.subject, previous.email
        else:
            raise ChatGPTAuthError("AUTH_OIDC", "Verified identity is required")
        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        if not isinstance(token_type, str) or token_type.lower() != "bearer":
            raise ChatGPTAuthError("AUTH_RESPONSE", "Token response requires the Bearer token type")
        if not isinstance(access_token, str) or not access_token:
            raise ChatGPTAuthError("AUTH_RESPONSE", "Token response requires a Bearer access token")
        try:
            expires_in = float(payload["expires_in"])
            if expires_in <= 0:
                raise ValueError("expires_in must be positive")
        except (ValueError, KeyError, TypeError) as exc:
            raise ChatGPTAuthError("AUTH_RESPONSE", self.redact(f"Invalid token expiry: {exc}")) from None
        # refresh 省略 scope 表示保留原授权；首次登录缺 scope 不推断获得了推理权限。
        if "scope" in payload and not isinstance(payload["scope"], str):
            raise ChatGPTAuthError("AUTH_RESPONSE", "Granted scope must be a space-separated string")
        scopes = (
            tuple(payload["scope"].split())
            if "scope" in payload
            else (previous.scopes if nonce is None and previous else ())
        )
        return _Credential(
            client_id=client_id,
            subject=subject,
            email=email,
            issuer=ISSUER,
            access_token=access_token,
            refresh_token=refresh_token,
            id_token=str(token or (previous.id_token if previous and nonce is None else "")),
            scopes=scopes,
            expires_at=time.time() + expires_in,
        )

    async def access_token(self) -> str:
        """锁内重读磁盘，保证不同进程不会用同一个旋转 refresh token 并发刷新。"""
        async with self.store.async_locked():
            data = self.store._read()
            credential = self.store._credential(data, self.account_id)
            # Runtime 首次使用后固定注册，外部 CLI 切账号不能把 A 的目录与 B 的 token 混用。
            if self.account_id is None:
                self.account_id = credential.client_id
            self._remember(credential)
            if not {DIRECT_SCOPE, "resource.invoke"}.issubset(credential.scopes):
                raise ChatGPTAuthError(
                    "AUTH_SCOPE", "ChatGPT plan usage was not granted; sign in again to authorize it"
                )
            if not credential.access_token:
                raise ChatGPTAuthError("AUTH_REQUIRED", "Selected ChatGPT account is signed out; sign in again")
            if credential.expires_at <= time.time() + 60:
                if not credential.refresh_token:
                    raise ChatGPTAuthError(
                        "AUTH_REQUIRED", "Access token expired without a renewable session; sign in again"
                    )
                try:
                    response = await self._request(
                        "POST",
                        TOKEN_URL,
                        data={
                            "grant_type": "refresh_token",
                            "client_id": credential.client_id,
                            "refresh_token": credential.refresh_token,
                            "resource": RESOURCE,
                        },
                    )
                except ChatGPTAuthError as exc:
                    if exc.oauth_code in TERMINAL_REFRESH_ERRORS:
                        # 服务端已确认会话无法恢复；清除令牌，身份/client 映射仍供本人重新登录。
                        data["accounts"][credential.client_id] = asdict(
                            replace(
                                credential,
                                access_token="",
                                refresh_token="",
                                id_token="",
                                expires_at=0,
                            )
                        )
                        self.store._write(data)
                    raise
                credential = await self._tokens(self._json(response), credential.client_id, None, credential)
                self._remember(credential)
                # 访问令牌、授权范围、到期时间与最新 refresh token 同时写入同一文件。
                data["accounts"][credential.client_id] = asdict(credential)
                self.store._write(data)
            if not {DIRECT_SCOPE, "resource.invoke"}.issubset(credential.scopes):
                raise ChatGPTAuthError("AUTH_SCOPE", "Refreshed grant does not authorize ChatGPT plan usage")
            return credential.access_token

    async def list_models(self) -> list[dict[str, object]]:
        """只返回当前账号官方目录中可展示的模型，保留服务器排序。"""
        token = await self.access_token()
        payload = self._json(
            await self._request("GET", f"{RESOURCE}/models", headers={"Authorization": f"Bearer {token}"})
        )
        models = payload.get("models")
        if not isinstance(models, list):
            raise ChatGPTAuthError("AUTH_MODELS", "Model catalog did not include a models array")
        result: list[dict[str, object]] = []
        for model in models:
            if not isinstance(model, dict):
                raise ChatGPTAuthError("AUTH_MODELS", "Invalid model catalog entry")
            if model.get("visibility") == "list":
                if not isinstance(model.get("slug"), str) or not isinstance(model.get("display_name"), str):
                    raise ChatGPTAuthError("AUTH_MODELS", "Listed model requires slug and display_name")
                result.append({"slug": model["slug"], "display_name": model["display_name"]})
        return result

    async def login(
        self,
        *,
        new_account: bool = False,
        timeout_seconds: float = 300,
        browser_opener: Callable[[str], object] | None = None,
    ) -> dict[str, object]:
        """启动 loopback 后打开系统浏览器；用户本人完成登录和授权。"""
        async with self.store.async_locked():
            data = self.store._read()
            self.store._write(data)
            host_id = str(data["ext_agent_host_id"])
            selected = self.account_id or data["selected_account"]
            pending = data.get("pending_registrations", [])
            previous = (
                self.store._credential(data, selected)
                if selected and selected not in pending and not new_account
                else None
            )
            # 未完成 code exchange 的 issued ID 仅作为 pending 保存，不能伪造已验证账号。
            returning_client = (
                previous.client_id
                if previous
                else (
                    selected
                    if selected in pending and not new_account
                    else (pending[-1] if pending and not selected and not new_account else None)
                )
            )
        if previous:
            self._remember(previous)
        # 每次尝试独立生成 state / nonce / verifier，绝不复用上一次的随机材料。
        state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        self._secrets.update((state, nonce, verifier))
        future: asyncio.Future[dict[str, str]] = asyncio.get_running_loop().create_future()

        async def callback(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            status, body = "400 Bad Request", "Authorization failed. Return to Trivae for details."
            try:
                request = (await asyncio.wait_for(reader.readline(), timeout=10)).decode("ascii").split()
                if len(request) != 3 or request[0] != "GET":
                    raise ChatGPTAuthError("AUTH_CALLBACK", "Expected HTTP GET callback")
                target = urlsplit(request[1])
                if target.path != "/auth/callback":
                    status, body = "404 Not Found", "Not found"
                elif not future.done():
                    query = parse_qs(target.query, keep_blank_values=True)
                    if any(len(values) != 1 for values in query.values()):
                        raise ChatGPTAuthError("AUTH_CALLBACK", "Duplicate OAuth callback parameters")
                    params = {key: values[0] for key, values in query.items()}
                    if not secrets.compare_digest(params.get("state", ""), state):
                        raise ChatGPTAuthError("AUTH_STATE", "Callback state does not match authorization attempt")
                    if params.get("error"):
                        raise ChatGPTAuthError(
                            "AUTH_DENIED", self.redact(params.get("error_description", params["error"]))
                        )
                    future.set_result(params)
                    status, body = "200 OK", "Authorization received. You can return to Trivae."
            except (ChatGPTAuthError, UnicodeError, TimeoutError) as exc:
                if not future.done():
                    future.set_exception(exc)
            finally:
                encoded = body.encode("utf-8")
                writer.write(
                    f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {len(encoded)}\r\nConnection: close\r\n\r\n".encode()
                    + encoded
                )
                await writer.drain()
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(callback, "127.0.0.1", 0)
        redirect_uri = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/auth/callback"
        params = {
            "client_id": returning_client or "dynamic_agent_client",
            "ext_agent_host_id": host_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": create_s256_code_challenge(verifier),
        }
        if previous:
            if previous.id_token:
                params["id_token_hint"] = previous.id_token
            if previous.email:
                params["login_hint"] = previous.email
            if DIRECT_SCOPE not in previous.scopes:
                # 用户明确重新登录以启用 plan usage 时重新请求 consent，普通重登录不强制弹窗。
                params["prompt"] = "consent"
        elif returning_client is None:
            params["agent_name_hint"] = "Trivae"
        try:
            # URL 可能含 ID token hint，禁止将它打印、记录或返回到 CLI。
            opened = (browser_opener or webbrowser.open)(f"{AUTHORIZE_URL}?{urlencode(params)}")
            if opened is False:
                raise ChatGPTAuthError("AUTH_BROWSER", "System browser could not be opened")
            try:
                callback_params = await asyncio.wait_for(future, timeout=timeout_seconds)
            except TimeoutError:
                raise ChatGPTAuthError(
                    "AUTH_TIMEOUT", "Browser authorization did not complete before timeout"
                ) from None
        finally:
            server.close()
            await server.wait_closed()
        supplied_client = callback_params.get("client_id")
        if returning_client:
            if supplied_client and supplied_client != returning_client:
                raise ChatGPTAuthError("AUTH_CLIENT", "Callback client ID differs from selected registration")
            client_id = returning_client
        else:
            if not supplied_client or supplied_client == "dynamic_agent_client":
                raise ChatGPTAuthError("AUTH_CLIENT", "New registration did not return an issued client ID")
            client_id = supplied_client
        code = callback_params.get("code")
        if not code:
            raise ChatGPTAuthError("AUTH_CALLBACK", "Authorization callback did not include a code")
        self._secrets.add(code)
        if previous is None:
            async with self.store.async_locked():
                pending_data = self.store._read()
                pending_ids = pending_data.setdefault("pending_registrations", [])
                if client_id not in pending_ids:
                    pending_ids.append(client_id)
                self.store._write(pending_data)
        response = await self._request(
            "POST",
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
                "resource": RESOURCE,
            },
        )
        credential = await self._tokens(self._json(response), client_id, nonce, previous)
        self._remember(credential)
        async with self.store.async_locked():
            current = self.store._read()
            if (
                client_id in current["accounts"]
                and self.store._credential(current, client_id).subject != credential.subject
            ):
                raise ChatGPTAuthError("AUTH_IDENTITY", "Issued client ID belongs to a different verified account")
            # 新尝试到这里已通过签名、nonce、client 和身份校验，才替换凭证并选为 active。
            current["accounts"][client_id] = asdict(credential)
            current["selected_account"] = client_id
            if client_id in current.get("pending_registrations", []):
                current["pending_registrations"].remove(client_id)
            self.store._write(current)
        # 此 manager 的后续 models / inference 都绑定刚验证成功的同一注册。
        self.account_id = credential.client_id
        return credential.metadata()

    async def logout(self) -> None:
        """尝试撤销 renewable session，然后清除令牌；保留注册身份和 host。"""
        failure: ChatGPTAuthError | None = None
        async with self.store.async_locked():
            data = self.store._read()
            credential = self.store._credential(data, self.account_id)
            self._remember(credential)
            try:
                if credential.refresh_token:
                    discovery = await self._discovery()
                    await self._request(
                        "POST",
                        str(discovery["revocation_endpoint"]),
                        data={
                            "token": credential.refresh_token,
                            "token_type_hint": "refresh_token",
                            "client_id": credential.client_id,
                        },
                    )
            except ChatGPTAuthError as exc:
                failure = exc
            # 即使远端撤销失败，也不能让用户退出后继续使用本地凭证。
            data["accounts"][credential.client_id] = asdict(
                replace(
                    credential,
                    access_token="",
                    refresh_token="",
                    id_token="",
                    expires_at=0,
                )
            )
            self.store._write(data)
        if failure:
            raise ChatGPTAuthError(
                "AUTH_REVOCATION",
                f"Local tokens cleared; remote revocation unconfirmed. Disconnect Trivae in ChatGPT Settings. {failure}",
            ) from None

    async def aclose(self) -> None:
        """只关闭认证层自己创建的 HTTP client。"""
        if self._owns_client:
            await self._client.aclose()
