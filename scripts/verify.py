from __future__ import annotations

import subprocess
import sys

COMMANDS: list[list[str]] = [
    [sys.executable, "-m", "ruff", "check", "."],
    [sys.executable, "-m", "ruff", "format", "--check", "."],
    [sys.executable, "-m", "mypy", "src", "solvers", "app", "tests"],
    [sys.executable, "-m", "pytest"],
    [sys.executable, "-m", "mkdocs", "build", "--strict"],
]


def main() -> None:
    for command in COMMANDS:
        print(f"\n==> {' '.join(command)}")
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
