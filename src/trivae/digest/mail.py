"""通过显式配置的 TLS SMTP 发件，不在日志或状态中保存邮箱授权码。"""

from __future__ import annotations

import os
import smtplib
import ssl
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from trivae.digest.contracts import TIMEZONE


@dataclass(frozen=True)
class MailSettings:
    """发件服务与收件人；授权码不进入对象的 repr。"""

    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sender: str = ""
    recipient: str = ""

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> MailSettings:
        """缺少必要配置时立即报出变量名，不换渠道或静默跳过发送。"""

        values = os.environ if environ is None else environ
        required = ("TRIVAE_SMTP_HOST", "TRIVAE_SMTP_USERNAME", "TRIVAE_SMTP_PASSWORD",
                    "TRIVAE_MAIL_FROM", "TRIVAE_MAIL_TO")
        missing = [name for name in required if not values.get(name, "").strip()]
        if missing:
            raise ValueError("邮件配置缺失：" + ", ".join(missing))
        return cls(values[required[0]], int(values.get("TRIVAE_SMTP_PORT", "465")),
                   values[required[1]], values[required[2]], values[required[3]], values[required[4]])


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
    # 直接使用已配置的 SSL 端口；证书校验保留，不尝试未配置的端口或明文连接。
    with smtplib.SMTP_SSL(settings.host, settings.port, timeout=30, context=ssl.create_default_context()) as client:
        client.login(settings.username, settings.password)
        refused = client.send_message(message, from_addr=settings.sender, to_addrs=[settings.recipient])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    return str(message["Message-ID"])
