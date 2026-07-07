#!/usr/bin/env python3
"""Generate a release SBOM for Tapio RollView."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator


PRODUCT_NAME = "Tapio RollView"
PACKAGE_NAME = "tapio-rollview"
PUBLISHER = "Tapio Measurement Technologies Oy"
LICENSE_ID = "GPL-3.0-or-later"
PROJECT_URL = "https://github.com/Tapio-Measurement-Technologies/tapio-rollview"
WEBSITE_URL = "https://www.tapiotechnologies.com"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def git_commit() -> str:
    env_sha = os.environ.get("GITHUB_SHA")
    if env_sha:
        return env_sha

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def target_platform() -> str:
    env_platform = os.environ.get("RUNNER_OS")
    if env_platform:
        return env_platform.lower()
    return platform.system().lower() or "unknown"


def upsert_property(properties: list[dict[str, str]], name: str, value: str) -> None:
    for item in properties:
        if item.get("name") == name:
            item["value"] = value
            return
    properties.append({"name": name, "value": value})


def run_cyclonedx(requirements: Path, output: Path, spec_version: str) -> None:
    cmd = [
        sys.executable,
        "-m",
        "cyclonedx_py",
        "requirements",
        str(requirements),
        "--spec-version",
        spec_version,
        "--output-format",
        "JSON",
        "--output-file",
        str(output),
        "--validate",
    ]
    subprocess.run(cmd, check=True)


def stamp_bom(
    bom_path: Path,
    version: str,
    commit_sha: str,
    build_platform: str,
    build_timestamp: str,
    requirements: Path,
) -> None:
    with bom_path.open("r", encoding="utf-8") as file:
        bom = json.load(file)

    metadata = bom.setdefault("metadata", {})
    metadata["timestamp"] = build_timestamp

    component = metadata.setdefault("component", {})
    component_ref = component.get("bom-ref") or f"pkg:generic/{PACKAGE_NAME}@{version}"
    component.update(
        {
            "type": "application",
            "bom-ref": component_ref,
            "name": PRODUCT_NAME,
            "version": version,
            "publisher": PUBLISHER,
            "purl": f"pkg:generic/{PACKAGE_NAME}@{version}",
            "licenses": [{"license": {"id": LICENSE_ID}}],
            "externalReferences": [
                {"type": "website", "url": WEBSITE_URL},
                {"type": "vcs", "url": PROJECT_URL},
            ],
        }
    )

    properties = metadata.setdefault("properties", [])
    upsert_property(properties, "tapio:sbom:commit-sha", commit_sha)
    upsert_property(properties, "tapio:sbom:platform", build_platform)
    upsert_property(properties, "tapio:sbom:requirements-file", str(requirements))
    upsert_property(properties, "tapio:sbom:generator", "cyclonedx-py")

    validate_bom(bom)
    serialized = json.dumps(bom, indent=2, sort_keys=True)
    validate_cyclonedx_schema(serialized, bom["specVersion"])

    with bom_path.open("w", encoding="utf-8") as file:
        file.write(serialized)
        file.write("\n")


def validate_bom(bom: dict) -> None:
    if bom.get("bomFormat") != "CycloneDX":
        raise ValueError("Generated file is not a CycloneDX BOM")
    if not bom.get("specVersion"):
        raise ValueError("Generated CycloneDX BOM is missing specVersion")
    if not bom.get("components"):
        raise ValueError("Generated CycloneDX BOM has no components")

    metadata = bom.get("metadata") or {}
    component = metadata.get("component") or {}
    if component.get("name") != PRODUCT_NAME:
        raise ValueError("Generated CycloneDX BOM has wrong root component")


def validate_cyclonedx_schema(serialized_bom: str, spec_version: str) -> None:
    schema_versions = {
        "1.6": SchemaVersion.V1_6,
        "1.7": SchemaVersion.V1_7,
    }
    validator = JsonStrictValidator(schema_versions[spec_version])
    validation_error = validator.validate_str(serialized_bom)
    if validation_error is not None:
        raise ValueError(f"CycloneDX schema validation failed: {validation_error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Tapio RollView CycloneDX SBOM.")
    parser.add_argument("--requirements", default="requirements.txt", help="Requirements file to inventory.")
    parser.add_argument("--output", required=True, help="Output CycloneDX JSON path.")
    parser.add_argument("--version", default=os.environ.get("GITHUB_REF_NAME", "0.0.0+local"))
    parser.add_argument("--commit-sha", default=git_commit())
    parser.add_argument("--platform", default=target_platform())
    parser.add_argument("--build-timestamp", default=utc_now())
    parser.add_argument("--spec-version", default="1.6", choices=["1.6", "1.7"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requirements = Path(args.requirements)
    output = Path(args.output)

    if not requirements.exists():
        raise FileNotFoundError(f"Requirements file not found: {requirements}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="rollview-sbom-",
        suffix=".json",
        dir=output.parent,
        delete=False,
    ) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        run_cyclonedx(requirements, temp_path, args.spec_version)
        stamp_bom(
            temp_path,
            version=args.version,
            commit_sha=args.commit_sha,
            build_platform=args.platform,
            build_timestamp=args.build_timestamp,
            requirements=requirements,
        )
        temp_path.replace(output)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    print(f"Generated CycloneDX SBOM: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
