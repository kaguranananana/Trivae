"""通过显式配置的 TLS SMTP 发件，不在日志或状态中保存邮箱授权码。"""

from __future__ import annotations

import http.client
import os
import smtplib
import socket
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from typing import Any, cast
from urllib.parse import urlsplit

from trivae.digest.contracts import TIMEZONE


class MailNotSubmittedError(RuntimeError):
    """SMTP连接或认证尚未完成，邮件确定没有提交，可在后续触发时继续发送。"""


@dataclass(frozen=True)
class MailSettings:
    """发件服务与收件人；授权码不进入对象的 repr。"""

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str = ""
    recipient: str = ""
    http_proxy: tuple[str, int] | None = field(default=None, repr=False)

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> MailSettings:
        """缺少必要配置时立即报出变量名，不换渠道或静默跳过发送。"""

        values = os.environ if environ is None else environ
        required = ("TRIVAE_SMTP_HOST", "TRIVAE_SMTP_USERNAME", "TRIVAE_SMTP_PASSWORD",
                    "TRIVAE_MAIL_FROM", "TRIVAE_MAIL_TO")
        missing = [name for name in required if not values.get(name, "").strip()]
        if missing:
            raise ValueError("邮件配置缺失：" + ", ".join(missing))
        proxy_address = None
        if proxy_url := values.get("TRIVAE_SMTP_HTTP_PROXY", "").strip():
            proxy = urlsplit(proxy_url)
            if proxy.scheme != "http" or not proxy.hostname or proxy.username is not None:
                raise ValueError("TRIVAE_SMTP_HTTP_PROXY 仅支持无认证的 http://主机:端口 代理")
            proxy_address = (proxy.hostname, proxy.port or 80)
        return cls(values[required[0]], int(values.get("TRIVAE_SMTP_PORT", "465")),
                   values[required[1]], values[required[2]], values[required[3]], values[required[4]], proxy_address)


class _SMTPHTTPProxy(smtplib.SMTP_SSL):
    """明确配置的HTTP CONNECT承载SMTP，TLS及主机名校验仍由标准库执行。"""

    def __init__(self, host: str, port: int, *, http_proxy: tuple[str, int],
                 timeout: float, context: ssl.SSLContext) -> None:
        self._http_proxy = http_proxy
        super().__init__(host, port, timeout=timeout, context=context)

    def _get_socket(self, host: str, port: int, timeout: Any) -> socket.socket:
        tunnel = http.client.HTTPConnection(*self._http_proxy, timeout=timeout)
        tunnel.set_tunnel(host, port)
        try:
            # 仅解析已配置的代理地址；SMTP域名交给隧道对端处理。
            tunnel.connect()
            return self.context.wrap_socket(cast(socket.socket, tunnel.sock), server_hostname=host)
        except Exception:
            tunnel.close()
            raise


def send_digest_mail(settings: MailSettings, *, subject: str, text: str, document: str) -> str:
    """发送一封含纯文本和 HTML 的邮件，只有 SMTP 接受收件人后才返回成功。"""

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.sender
    message["To"] = settings.recipient
    message["Date"] = format_datetime(datetime.now(TIMEZONE))
    message["Message-ID"] = make_msgid(domain=settings.sender.rsplit("@", 1)[-1])
    message.set_content(text)
    message.add_alternative(document, subtype="html")
    # 连接路径只取显式配置，失败不会在代理、直连或端口之间自动切换。
    try:
        context = ssl.create_default_context()
        connection = (
            _SMTPHTTPProxy(settings.host, settings.port, http_proxy=settings.http_proxy, timeout=30, context=context)
            if settings.http_proxy else smtplib.SMTP_SSL(settings.host, settings.port, timeout=30, context=context)
        )
    except (OSError, smtplib.SMTPException, http.client.HTTPException) as exc:
        raise MailNotSubmittedError(f"SMTP连接失败，邮件尚未提交：{exc}") from exc
    with connection as client:
        try:
            client.login(settings.username, settings.password)
        except (OSError, smtplib.SMTPException) as exc:
            raise MailNotSubmittedError(f"SMTP认证失败，邮件尚未提交：{exc}") from exc
        # 从此处开始可能已发送DATA；传输中断仍是待确认失败，不能自动重复发送。
        refused = client.send_message(message, from_addr=settings.sender, to_addrs=[settings.recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    return str(message["Message-ID"])
