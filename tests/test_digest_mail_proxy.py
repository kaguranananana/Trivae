"""真实DNS失败案例：邮件显式走HTTP隧道，TLS目标仍是原SMTP主机。"""

from __future__ import annotations

import socket
import socketserver
import ssl
import threading

import pytest

from trivae.digest.mail import MailNotSubmittedError, MailSettings, send_digest_mail


@pytest.mark.parametrize("proxy_status", [200, 503])
def test_explicit_mail_proxy_avoids_failed_local_dns_and_preserves_tls(
    monkeypatch: pytest.MonkeyPatch, proxy_status: int,
) -> None:
    """使用真实本机隧道和SMTP对话，只替换TLS握手，失败不切回直连。"""

    commands: list[bytes] = []
    bodies: list[bytes] = []
    tls_contexts: list[ssl.SSLContext] = []

    class Proxy(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            commands.append(self.rfile.readline().strip())
            while self.rfile.readline() != b"\r\n":
                pass
            if proxy_status != 200:
                self.wfile.write(b"HTTP/1.1 503 Unavailable\r\n\r\n")
                return
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            # TLS测试替身发出标记后才给SMTP欢迎语，避免HTTP响应预读掉欢迎语。
            assert self.rfile.readline() == b"TEST_TLS_HANDSHAKE\r\n"
            self.wfile.write(b"220 loopback SMTP ready\r\n")
            while line := self.rfile.readline():
                verb = line.split(maxsplit=1)[0].upper()
                commands.append(verb)
                if verb == b"EHLO":
                    self.wfile.write(b"250-loopback\r\n250 AUTH PLAIN\r\n")
                elif verb == b"AUTH":
                    self.wfile.write(b"235 authenticated\r\n")
                elif verb == b"DATA":
                    self.wfile.write(b"354 send message\r\n")
                    body = []
                    while (part := self.rfile.readline()) != b".\r\n":
                        body.append(part)
                    bodies.append(b"".join(body))
                    self.wfile.write(b"250 accepted\r\n")
                elif verb == b"QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    real_resolver = socket.getaddrinfo

    def resolver(host: str, *args: object, **kwargs: object) -> list:
        if host == "smtp.qq.com":
            raise socket.gaierror(8, "observed system DNS failure")
        return real_resolver(host, *args, **kwargs)

    def tls_handshake(context: ssl.SSLContext, sock: socket.socket, *, server_hostname: str) -> socket.socket:
        assert server_hostname == "smtp.qq.com"
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        tls_contexts.append(context)
        sock.sendall(b"TEST_TLS_HANDSHAKE\r\n")
        return sock

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    monkeypatch.setattr(ssl.SSLContext, "wrap_socket", tls_handshake)
    with Server(("127.0.0.1", 0), Proxy) as server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        try:
            settings = MailSettings.from_environment({
                "TRIVAE_SMTP_HOST": "smtp.qq.com", "TRIVAE_SMTP_USERNAME": "test-user",
                "TRIVAE_SMTP_PASSWORD": "test-password", "TRIVAE_MAIL_FROM": "from@example.com",
                "TRIVAE_MAIL_TO": "to@example.com",
                "TRIVAE_SMTP_HTTP_PROXY": f"http://127.0.0.1:{server.server_address[1]}",
            })
            if proxy_status == 200:
                result = send_digest_mail(settings, subject="digest", text="body", document="<p>body</p>")
                assert result.startswith("<") and len(bodies) == 1
                assert b"AUTH" in commands and b"DATA" in commands and len(tls_contexts) == 1
            else:
                with pytest.raises(MailNotSubmittedError, match="503"):
                    send_digest_mail(settings, subject="digest", text="body", document="<p>body</p>")
                assert not bodies and not tls_contexts and b"AUTH" not in commands
            assert commands[0].startswith(b"CONNECT smtp.qq.com:465 HTTP/")
        finally:
            server.shutdown()
            thread.join()
