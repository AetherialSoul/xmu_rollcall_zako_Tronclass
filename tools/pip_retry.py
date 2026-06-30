from __future__ import annotations

import subprocess
import sys
import time


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: pip_retry.py <pip install args...>")
        return 2

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
        *sys.argv[1:],
    ]
    for attempt in range(1, 4):
        result = subprocess.run(command)
        if result.returncode == 0:
            return 0
        if attempt == 3:
            return result.returncode
        print(f"pip install failed. Retrying attempt {attempt + 1}/3...")
        time.sleep(3)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
