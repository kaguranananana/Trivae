from __future__ import annotations

import os
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from trivae.config.dotenv import DotenvError, load_environment_file
from trivae.config.settings import load_settings


@contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    """临时切换工作目录，确保默认 `.env` 测试不依赖仓库真实配置。"""

    original = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original)


class DotenvTests(unittest.TestCase):
    """验证 CLI dotenv 的边界、优先级和显式错误。"""

    def test_default_file_supports_comments_quotes_export_and_literal_shell_text(self) -> None:
        """默认文件只解析赋值文本，不执行值中的 shell 表达式。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "\n".join(
                    (
                        "# comment",
                        "export TRIVAE_MODEL_PROVIDER=\"opencode-go\"",
                        "TRIVAE_MODEL_NAME='deepseek-v4-flash'",
                        "TRIVAE_MODEL_BASE_URL=https://example.test/v1",
                        "TRIVAE_MODEL_API_KEY=$(printf 'not-executed')",
                        "TRIVAE_MAX_TURNS=9 # inline comment",
                    )
                ),
                encoding="utf-8",
            )
            values: dict[str, str] = {}
            with _working_directory(root):
                loaded_path = load_environment_file(environ=values)

        self.assertIsNotNone(loaded_path)
        assert loaded_path is not None
        self.assertEqual(loaded_path.resolve(), (root / ".env").resolve())
        self.assertEqual(values["TRIVAE_MODEL_PROVIDER"], "opencode-go")
        self.assertEqual(values["TRIVAE_MODEL_NAME"], "deepseek-v4-flash")
        self.assertEqual(values["TRIVAE_MODEL_BASE_URL"], "https://example.test/v1")
        self.assertEqual(values["TRIVAE_MODEL_API_KEY"], "$(printf 'not-executed')")
        self.assertEqual(values["TRIVAE_MAX_TURNS"], "9")

    def test_existing_environment_values_win_including_empty_values(self) -> None:
        """进程环境变量优先，空值也不能被 dotenv 悄悄补写。"""

        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "custom.env"
            env_file.write_text(
                "TRIVAE_MODEL_NAME=from-file\nTRIVAE_MODEL_PROVIDER=opencode-go\n",
                encoding="utf-8",
            )
            values = {"TRIVAE_MODEL_NAME": "", "TRIVAE_MODEL_PROVIDER": "from-process"}
            load_environment_file(env_file, environ=values)

        self.assertEqual(values["TRIVAE_MODEL_NAME"], "")
        self.assertEqual(values["TRIVAE_MODEL_PROVIDER"], "from-process")

    def test_duplicate_file_assignments_use_last_value(self) -> None:
        """同一文件中的重复键按文件顺序取最后一次赋值。"""

        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "custom.env"
            env_file.write_text("VALUE=first\nVALUE=second\n", encoding="utf-8")
            values: dict[str, str] = {}
            load_environment_file(env_file, environ=values)

        self.assertEqual(values, {"VALUE": "second"})

    def test_missing_default_file_is_optional_but_missing_explicit_file_is_error(self) -> None:
        """默认文件缺失保持旧启动语义，显式文件缺失必须可见。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values: dict[str, str] = {}
            with _working_directory(root):
                self.assertIsNone(load_environment_file(environ=values))
            with self.assertRaisesRegex(DotenvError, "dotenv file not found"):
                load_environment_file(root / "missing.env", environ=values)

        self.assertEqual(values, {})

    def test_parse_errors_are_reported_before_any_assignment_is_injected(self) -> None:
        """格式错误不能留下部分环境状态，也不能被静默忽略。"""

        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "broken.env"
            env_file.write_text("GOOD=value\nBROKEN\n", encoding="utf-8")
            values: dict[str, str] = {}
            with self.assertRaisesRegex(DotenvError, r"broken\.env:2"):
                load_environment_file(env_file, environ=values)

        self.assertEqual(values, {})

    def test_invalid_variable_name_and_unterminated_quote_are_errors(self) -> None:
        """变量名和引号错误都必须在 Provider 创建前暴露。"""

        cases = ("NOT-VALID=value\n", 'VALUE="unterminated\n')
        for content in cases:
            with self.subTest(content=content):
                with tempfile.TemporaryDirectory() as directory:
                    env_file = Path(directory) / "broken.env"
                    env_file.write_text(content, encoding="utf-8")
                    with self.assertRaises(DotenvError):
                        load_environment_file(env_file, environ={})

    def test_load_settings_does_not_read_default_dotenv_implicitly(self) -> None:
        """默认模型目录不等于隐式加载工作目录里的 `.env`。"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text(
                "TRIVAE_MODEL_API_KEY=from-file\nTRIVAE_MODEL_NAME=from-file\n",
                encoding="utf-8",
            )
            with _working_directory(root), patch.dict(os.environ, {}, clear=True):
                settings = load_settings()
                self.assertEqual(settings.model_profile, "gpt-plus")
                self.assertEqual(settings.model_name, "gpt-6.1-sol")


if __name__ == "__main__":
    unittest.main()
