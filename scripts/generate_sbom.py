#!/usr/bin/env python3
"""Generate a release SBOM for Tapio RollView."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
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


def normalized_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def direct_requirement_names(requirements: Path) -> set[str]:
    names: set[str] = set()
    for raw_line in requirements.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        match = re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if match is None:
            raise ValueError(f"Cannot parse direct requirement: {raw_line}")
        names.add(normalized_package_name(match.group()))
    return names


def connect_root_dependencies(
    bom: dict,
    root_ref: str,
    direct_requirements: Path,
    additional_refs: tuple[str, ...] = (),
) -> None:
    direct_names = direct_requirement_names(direct_requirements)
    direct_refs = sorted(
        component["bom-ref"]
        for component in bom.get("components", [])
        if normalized_package_name(component.get("name", "")) in direct_names
    )
    found_names = {
        normalized_package_name(component.get("name", ""))
        for component in bom.get("components", [])
        if component.get("bom-ref") in direct_refs
    }
    missing_names = direct_names - found_names
    if missing_names:
        raise ValueError(
            "Direct requirements missing from generated SBOM: "
            + ", ".join(sorted(missing_names))
        )

    dependencies = bom.setdefault("dependencies", [])
    root_dependency = next(
        (dependency for dependency in dependencies if dependency.get("ref") == root_ref),
        None,
    )
    if root_dependency is None:
        root_dependency = {"ref": root_ref}
        dependencies.append(root_dependency)
    root_dependency["dependsOn"] = sorted({*direct_refs, *additional_refs})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def installed_pyinstaller_version() -> str:
    try:
        return importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(
            "PyInstaller must be installed when generating an artifact SBOM"
        ) from error


def add_embedded_runtime_components(
    bom: dict,
    pyinstaller_version: str,
) -> tuple[str, str]:
    python_version = platform.python_version()
    python_ref = f"pkg:generic/python@{python_version}"
    bootloader_ref = f"pkg:generic/pyinstaller-bootloader@{pyinstaller_version}"
    components = bom.setdefault("components", [])
    components.extend(
        [
            {
                "type": "framework",
                "bom-ref": python_ref,
                "name": "Python",
                "version": python_version,
                "purl": python_ref,
                "properties": [
                    {"name": "tapio:sbom:embedded-part", "value": "interpreter"}
                ],
            },
            {
                "type": "framework",
                "bom-ref": bootloader_ref,
                "name": "PyInstaller bootloader",
                "version": pyinstaller_version,
                "purl": bootloader_ref,
                "externalReferences": [
                    {
                        "type": "vcs",
                        "url": "https://github.com/pyinstaller/pyinstaller",
                    }
                ],
                "properties": [
                    {"name": "tapio:sbom:embedded-part", "value": "bootloader"}
                ],
            },
        ]
    )

    dependencies = bom.setdefault("dependencies", [])
    existing_refs = {dependency.get("ref") for dependency in dependencies}
    for component_ref in (python_ref, bootloader_ref):
        if component_ref not in existing_refs:
            dependencies.append({"ref": component_ref})
    return python_ref, bootloader_ref


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
    direct_requirements: Path,
    artifact: Path | None,
    pyinstaller_version: str | None,
) -> None:
    with bom_path.open("r", encoding="utf-8") as file:
        bom = json.load(file)

    metadata = bom.setdefault("metadata", {})
    metadata["timestamp"] = build_timestamp

    component = metadata.setdefault("component", {})
    component_ref = f"pkg:generic/{PACKAGE_NAME}@{version}"
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

    embedded_refs: tuple[str, ...] = ()
    if artifact is not None:
        component["hashes"] = [{"alg": "SHA-256", "content": sha256_file(artifact)}]
        embedded_refs = add_embedded_runtime_components(
            bom,
            pyinstaller_version or installed_pyinstaller_version(),
        )

    properties = metadata.setdefault("properties", [])
    upsert_property(properties, "tapio:sbom:commit-sha", commit_sha)
    upsert_property(properties, "tapio:sbom:platform", build_platform)
    upsert_property(properties, "tapio:sbom:requirements-file", str(requirements))
    upsert_property(properties, "tapio:sbom:generator", "cyclonedx-py")
    if artifact is not None:
        upsert_property(properties, "tapio:sbom:artifact-name", artifact.name)
        upsert_property(properties, "tapio:sbom:artifact-size", str(artifact.stat().st_size))

    connect_root_dependencies(
        bom,
        component_ref,
        direct_requirements,
        embedded_refs,
    )

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

    root_ref = component.get("bom-ref")
    root_dependency = next(
        (
            dependency
            for dependency in bom.get("dependencies", [])
            if dependency.get("ref") == root_ref
        ),
        None,
    )
    if not root_dependency or not root_dependency.get("dependsOn"):
        raise ValueError("Generated CycloneDX BOM has no root dependency graph")


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
    parser.add_argument(
        "--direct-requirements",
        default="requirements.in",
        help="Direct requirements file used to connect the root dependency graph.",
    )
    parser.add_argument("--output", required=True, help="Output CycloneDX JSON path.")
    parser.add_argument(
        "--artifact",
        help="Final executable represented by this SBOM; adds its SHA-256 digest.",
    )
    parser.add_argument(
        "--pyinstaller-version",
        help="PyInstaller version embedded in artifact (normally detected).",
    )
    parser.add_argument("--version", default=os.environ.get("GITHUB_REF_NAME", "0.0.0+local"))
    parser.add_argument("--commit-sha", default=git_commit())
    parser.add_argument("--platform", default=target_platform())
    parser.add_argument("--build-timestamp", default=utc_now())
    parser.add_argument("--spec-version", default="1.6", choices=["1.6", "1.7"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requirements = Path(args.requirements)
    direct_requirements = Path(args.direct_requirements)
    artifact = Path(args.artifact) if args.artifact else None
    output = Path(args.output)

    if not requirements.exists():
        raise FileNotFoundError(f"Requirements file not found: {requirements}")
    if not direct_requirements.exists():
        raise FileNotFoundError(
            f"Direct requirements file not found: {direct_requirements}"
        )
    if artifact is not None and not artifact.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact}")

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
            direct_requirements=direct_requirements,
            artifact=artifact,
            pyinstaller_version=args.pyinstaller_version,
        )
        temp_path.replace(output)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    print(f"Generated CycloneDX SBOM: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
