#!/usr/bin/env python3
"""Compile hashed Python requirement lock files."""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOCK_FILES = (
    (PROJECT_ROOT / "requirements.in", PROJECT_ROOT / "requirements.txt"),
    (PROJECT_ROOT / "requirements-build.in", PROJECT_ROOT / "requirements-build.txt"),
    (PROJECT_ROOT / "requirements-dev.in", PROJECT_ROOT / "requirements-dev.txt"),
)
SUPPORTED_PYTHON = (3, 12)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate hashed runtime, build, and development requirement files."
    )
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade all dependencies allowed by the input files.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check whether lock files are current without changing them.",
    )
    return parser.parse_args()


def validate_environment() -> None:
    if sys.version_info[:2] != SUPPORTED_PYTHON:
        version = ".".join(map(str, sys.version_info[:2]))
        raise RuntimeError(
            f"Requirements must be compiled with Python 3.12; current Python is {version}"
        )

    if importlib.util.find_spec("piptools") is None:
        raise RuntimeError(
            "pip-tools is required; run: python -m pip install -r requirements-dev.txt"
        )


def compile_lock(source: Path, output: Path, upgrade: bool) -> None:
    command = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--quiet",
        "--generate-hashes",
        "--allow-unsafe",
        "--resolver=backtracking",
        "--strip-extras",
        "--annotation-style=split",
        f"--cache-dir={output.parent / '.cache'}",
        f"--output-file={output}",
    ]
    if upgrade:
        command.append("--upgrade")
    command.append(source.name)

    environment = os.environ.copy()
    environment["CUSTOM_COMPILE_COMMAND"] = "python scripts/compile_requirements.py"
    subprocess.run(command, cwd=PROJECT_ROOT, env=environment, check=True)


def main() -> int:
    args = parse_args()
    validate_environment()

    with tempfile.TemporaryDirectory(prefix=".requirements-", dir=PROJECT_ROOT) as temp_dir:
        temp_root = Path(temp_dir)
        generated_files: list[tuple[Path, Path]] = []

        for source, destination in LOCK_FILES:
            temporary_output = temp_root / destination.name
            if destination.exists():
                shutil.copy2(destination, temporary_output)
            compile_lock(source, temporary_output, args.upgrade)
            generated_files.append((temporary_output, destination))

        changed = [
            destination
            for temporary_output, destination in generated_files
            if not destination.exists()
            or temporary_output.read_bytes() != destination.read_bytes()
        ]

        if args.check:
            if changed:
                for path in changed:
                    print(f"Outdated requirements lock: {path.name}", file=sys.stderr)
                return 1
            print("Requirements locks are current")
            return 0

        for temporary_output, destination in generated_files:
            temporary_output.replace(destination)
            print(f"Generated {destination.name}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
