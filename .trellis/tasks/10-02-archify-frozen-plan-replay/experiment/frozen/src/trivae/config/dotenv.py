"""CLI 专用的轻量 dotenv 读取器；不改变库层配置读取边界。"""

from __future__ import annotations

import ast
import os
import re
import stat
from collections.abc import MutableMapping
from pathlib import Path

_ENV_FILE_NAME = ".env"
_ENV_KEY_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class DotenvError(ValueError):
    """dotenv 文件不存在、不可读或格式非法。"""


def load_environment_file(
    path: Path | None = None,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> Path | None:
    """读取 dotenv 并注入缺失环境变量；未传 path 时默认寻找当前目录 `.env`。"""

    # 只有 CLI 显式调用这个函数时才产生文件系统读取，load_settings 本身仍是纯读取器。
    target = Path.cwd() / _ENV_FILE_NAME if path is None else path
    # 调用方传入 path 代表用户明确要求该文件存在，默认路径则允许不存在。
    explicit_path = path is not None
    try:
        target_mode = target.stat().st_mode
    except FileNotFoundError:
        if explicit_path:
            raise DotenvError(f"dotenv file not found: {target}")
        return None
    except OSError as exc:
        detail = exc.strerror or type(exc).__name__
        raise DotenvError(f"cannot inspect dotenv file {target}: {detail}") from exc
    # 目录或其他特殊文件不能被当作 dotenv 解析，提前暴露启动配置错误。
    if not stat.S_ISREG(target_mode):
        raise DotenvError(f"dotenv path is not a file: {target}")

    try:
        # 固定 UTF-8 读取，避免不同终端 locale 让同一配置产生不同结果。
        content = target.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise DotenvError(f"dotenv file is not valid UTF-8: {target}") from exc
    except OSError as exc:
        detail = exc.strerror or type(exc).__name__
        raise DotenvError(f"cannot read dotenv file {target}: {detail}") from exc

    # 先完整解析再注入，确保格式错误不会留下半份环境配置。
    assignments = _parse_dotenv(content, path=target)
    values = os.environ if environ is None else environ
    for name, value in assignments.items():
        # setdefault 保证 shell 显式值（包括空字符串）优先于文件值。
        values.setdefault(name, value)
    return target


def _parse_dotenv(content: str, *, path: Path) -> dict[str, str]:
    """解析有限且可审计的 KEY=VALUE 语法，不执行 shell 表达式。"""

    assignments: dict[str, str] = {}
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        # 空行和行首注释不产生配置项。
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # 兼容常见 dotenv 的 export 前缀，但只移除文本前缀，不执行 export。
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            raise DotenvError(f"invalid dotenv assignment at {path}:{line_number}")

        # 只按第一个等号拆分，以保留 URL、token 或表达式中的后续等号。
        raw_name, raw_value = line.split("=", maxsplit=1)
        name = raw_name.strip()
        if _ENV_KEY_PATTERN.fullmatch(name) is None:
            raise DotenvError(f"invalid dotenv variable name at {path}:{line_number}")
        # 后出现的同名键覆盖前一行，符合 dotenv 文件的顺序语义。
        assignments[name] = _parse_value(raw_value.strip(), path=path, line_number=line_number)
    return assignments


def _parse_value(raw_value: str, *, path: Path, line_number: int) -> str:
    """解析未引号值和完整单/双引号值；拒绝引号后隐藏的额外文本。"""

    if not raw_value:
        return ""
    if raw_value[0] not in {"'", '"'}:
        # 非引号值支持空白后的行尾注释，但保留 token 内的 `#` 字符。
        return _strip_unquoted_comment(raw_value).strip()

    quote = raw_value[0]
    closing_index = _find_closing_quote(raw_value, quote)
    if closing_index is None:
        raise DotenvError(f"unterminated dotenv value at {path}:{line_number}")
    suffix = raw_value[closing_index + 1 :].strip()
    if suffix and not suffix.startswith("#"):
        raise DotenvError(f"unexpected text after dotenv value at {path}:{line_number}")

    quoted = raw_value[: closing_index + 1]
    if quote == "'":
        # 单引号按 dotenv 常见语义保持字面内容，不展开反斜杠或变量。
        return quoted[1:-1]
    try:
        # literal_eval 只解释 Python 字符串转义，不会执行函数或 shell 命令。
        value = ast.literal_eval(quoted)
    except (SyntaxError, ValueError) as exc:
        raise DotenvError(f"invalid quoted dotenv value at {path}:{line_number}") from exc
    if not isinstance(value, str):
        raise DotenvError(f"invalid quoted dotenv value at {path}:{line_number}")
    return value


def _find_closing_quote(raw_value: str, quote: str) -> int | None:
    """查找未被双引号转义的结束引号。"""

    escaped = False
    for index, character in enumerate(raw_value[1:], start=1):
        if quote == '"' and escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if character == quote:
            return index
    return None


def _strip_unquoted_comment(raw_value: str) -> str:
    """只移除由空白引出的行尾注释，避免破坏值中的 `#`。"""

    for index, character in enumerate(raw_value):
        if character == "#" and (index == 0 or raw_value[index - 1].isspace()):
            return raw_value[:index]
    return raw_value
