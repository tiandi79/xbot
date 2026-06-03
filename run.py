#!/usr/bin/env python3
"""
xbot 一键入口（在项目根目录执行）:

    python run.py
    python run.py --dry-run
    python run.py --skip-chrome          # 不启动 Chrome，仅连接已有 CDP
    python run.py --max-comments 2       # 其余参数传给 auto_browse_comment.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
START_PS1 = ROOT / "scripts" / "start_chrome_cdp.ps1"
MAIN_SCRIPT = ROOT / "scripts" / "auto_browse_comment.py"


def _run(cmd: list[str]) -> int:
    print(f"[xbot] {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=ROOT).returncode


def main() -> None:
    argv = sys.argv[1:]
    skip_chrome = "--skip-chrome" in argv
    argv = [a for a in argv if a != "--skip-chrome"]
    if "-h" in argv or "--help" in argv:
        skip_chrome = True

    if not skip_chrome:
        if not START_PS1.is_file():
            print(f"[xbot] ERROR: missing {START_PS1}")
            sys.exit(1)
        code = _run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(START_PS1),
            ]
        )
        if code != 0:
            sys.exit(code)
        print()

    if not MAIN_SCRIPT.is_file():
        print(f"[xbot] ERROR: missing {MAIN_SCRIPT}")
        sys.exit(1)

    code = _run([sys.executable, str(MAIN_SCRIPT), *argv])
    sys.exit(code)


if __name__ == "__main__":
    main()
