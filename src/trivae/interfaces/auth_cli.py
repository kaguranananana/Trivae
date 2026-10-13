"""CLI 认证命令只展示安全账号状态和模型目录。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from trivae.auth import ChatGPTAuthError, ChatGPTAuthManager, ChatGPTAuthStore


def configure_auth_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """将 auth 子命令挂入现有 CLI，不在 parser 构造时读凭证。"""
    parser = subparsers.add_parser("auth", help="Sign in with ChatGPT and manage local accounts")
    commands = parser.add_subparsers(dest="auth_command", required=True)
    for command in ("login", "status", "logout", "models", "select"):
        child = commands.add_parser(command)
        child.add_argument("--provider", choices=("chatgpt",), default="chatgpt")
        child.add_argument("--account", help="Issued client ID shown by auth status", required=command == "select")
        if command == "login":
            child.add_argument("--new-account", action="store_true", help="Register another account or workspace")
            child.add_argument("--timeout", type=float, default=300, help="Browser authorization timeout in seconds")


async def _execute(args: argparse.Namespace) -> dict[str, object] | list[dict[str, object]]:
    store = ChatGPTAuthStore()
    manager = ChatGPTAuthManager(store, account_id=args.account)
    try:
        if args.auth_command == "login":
            print("Continue with ChatGPT: 请在系统浏览器中本人完成登录与授权。", flush=True)
            return await manager.login(new_account=args.new_account, timeout_seconds=args.timeout)
        if args.auth_command == "logout":
            await manager.logout()
        elif args.auth_command == "models":
            return await manager.list_models()
        elif args.auth_command == "select":
            store.select_account(args.account)
        return store.status()
    finally:
        await manager.aclose()


def run_auth_command(args: argparse.Namespace) -> int:
    """非零退出明确报告 OAuth 根因，不输出包含 ID hint 的授权 URL。"""
    try:
        result = asyncio.run(_execute(args))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ChatGPTAuthError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
