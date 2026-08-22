"""支持 `python -m trivae` 启动薄 CLI。"""

from trivae.interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
