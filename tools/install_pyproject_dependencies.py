from __future__ import annotations

import subprocess
import sys
import tomllib
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: install_pyproject_dependencies.py <pyproject.toml>")
        return 2

    pyproject = Path(sys.argv[1]).resolve()
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = data.get("project", {}).get("dependencies", []) or []
    optional = data.get("project", {}).get("optional-dependencies", {}) or {}
    for group_dependencies in optional.values():
        dependencies.extend(group_dependencies or [])

    if not dependencies:
        print(f"No pyproject dependencies found in {pyproject}")
        return 0

    print(f"Installing dependencies from {pyproject}:")
    for dependency in dependencies:
        print(f"  - {dependency}")

    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--retries",
        "5",
        "--timeout",
        "120",
        "--prefer-binary",
        *dependencies,
    ]
    for attempt in range(1, 4):
        try:
            subprocess.check_call(command)
            return 0
        except subprocess.CalledProcessError:
            if attempt == 3:
                raise
            print(f"pip install failed. Retrying attempt {attempt + 1}/3...")
            time.sleep(3)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
