from __future__ import annotations

import argparse
import importlib
import py_compile
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def check(condition: bool, ok: str, fail: str, errors: list[str]) -> None:
    if condition:
        print(f"[OK] {ok}")
    else:
        print(f"[FAIL] {fail}")
        errors.append(fail)


def check_import(module: str, errors: list[str]) -> None:
    try:
        importlib.import_module(module)
    except Exception as exc:
        print(f"[FAIL] import {module}: {exc}")
        errors.append(f"import {module}")
    else:
        print(f"[OK] import {module}")


def compile_file(path: Path, errors: list[str]) -> None:
    try:
        py_compile.compile(str(path), doraise=True)
    except Exception as exc:
        print(f"[FAIL] compile {path.relative_to(ROOT)}: {exc}")
        errors.append(f"compile {path.relative_to(ROOT)}")
    else:
        print(f"[OK] compile {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="also require optional integrations")
    args = parser.parse_args()

    errors: list[str] = []

    check(
        sys.version_info >= (3, 11),
        f"Python {sys.version.split()[0]}",
        "Python 3.11+ is required",
        errors,
    )

    for relative in (
        "zako_app_V2.0.py",
        "zako_get_rollcall.py",
        "requirements.txt",
        "account.example.json",
        "integrations/score_query/browser_query.py",
        "integrations/score_query/config.yaml.example",
    ):
        path = ROOT / relative
        check(path.exists(), f"found {relative}", f"missing {relative}", errors)

    for module in (
        "customtkinter",
        "requests",
        "playwright.async_api",
        "yaml",
        "bs4",
        "PIL",
        "Crypto",
        "Cryptodome",
        "httpx",
    ):
        check_import(module, errors)

    for relative in (
        "zako_app_V2.0.py",
        "zako_get_rollcall.py",
        "integrations/score_query/browser_query.py",
        "tools/iqa_start_integrated.py",
        "tools/install_pyproject_dependencies.py",
        "tools/pip_retry.py",
    ):
        compile_file(ROOT / relative, errors)

    if args.full:
        required_optional = (
            "integrations/iqa_helper/main.py",
            "integrations/iqa_helper/start.bat",
            "integrations/iqa_helper/start_integrated.py",
            "integrations/course_helper/client.py",
            "integrations/course_helper/config/user.yaml",
        )
        for relative in required_optional:
            path = ROOT / relative
            check(path.exists(), f"found {relative}", f"missing {relative}", errors)

        optional_compile = (
            "integrations/iqa_helper/start_integrated.py",
            "integrations/course_helper/client.py",
            "integrations/course_helper/captcha.py",
        )
        for relative in optional_compile:
            path = ROOT / relative
            if path.exists():
                compile_file(path, errors)

    if errors:
        print()
        print("Install verification failed:")
        for item in errors:
            print(f"  - {item}")
        return 1

    print()
    print("Install verification succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
