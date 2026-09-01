#!/usr/bin/env python3
"""Take a new version of the Tapio Design System's token file.

    python scripts/sync_design_system.py --design-system /path/to/design-system
    python scripts/sync_design_system.py --design-system ... --check

RollView carries ``src/theme/tapio-tokens.json`` — the design system's own token
file, byte for byte — and ``src/theme/rollview-tokens.json``, which holds what
RollView adds and records the hash of the copy. Neither is edited by hand.

Nothing in the application, the tests or the build reads the design system: the
copy is what RollView ships and what it is checked against, so a machine without
the design system checked out builds and tests exactly the same. This script is
the one place that wants it, it is run deliberately, and it has to be told where
it is — there is no assumed path and no fallback.

It answers the question the old arrangement could not: *is the colour on this
screen still the colour the system says it is?* Before it, RollView held a
hand-restructured copy of the token file, and a value that moved upstream simply
never arrived — nothing compared the two, so nothing could report it. Now the
copy is verbatim, so comparing them is a diff.

``--check`` reports and exits non-zero without writing anything. The other
direction — somebody editing the vendored file in place — is caught without the
design system at all: ``test_theme_tokens.py`` checks the recorded hash against
the copy on every run.
"""

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
THEME = REPO / "src" / "theme"
VENDORED = THEME / "tapio-tokens.json"
OVERLAY = THEME / "rollview-tokens.json"

ENV_VAR = "TAPIO_DESIGN_SYSTEM"


def design_system_path(argument=None):
    """Where to read the system from. Given explicitly or not at all."""
    for candidate in (argument, os.environ.get(ENV_VAR)):
        if candidate:
            path = pathlib.Path(candidate).expanduser()
            return path if (path / "tokens" / "tokens.json").is_file() else None
    return None


def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def flatten(document, prefix=""):
    """Every leaf of the token document, as ``path -> value``.

    A dict of dicts of lists compares badly; a flat mapping compares exactly,
    and names the token that moved rather than the block it sits in.
    """
    flat = {}
    if isinstance(document, dict):
        for key, value in document.items():
            flat.update(flatten(value, f"{prefix}.{key}" if prefix else key))
    elif isinstance(document, list):
        for index, value in enumerate(document):
            flat.update(flatten(value, f"{prefix}[{index}]"))
    else:
        flat[prefix] = document
    return flat


def differences(old, new):
    """``(moved, added, dropped)`` between two token documents."""
    before, after = flatten(old), flatten(new)
    moved = sorted(
        (key, before[key], after[key])
        for key in before.keys() & after.keys()
        if before[key] != after[key]
    )
    return moved, sorted(after.keys() - before.keys()), sorted(before.keys() - after.keys())


def report(moved, added, dropped, upstream_version, vendored_version):
    lines = []
    if upstream_version != vendored_version:
        lines.append(f"version {vendored_version} -> {upstream_version}")
    for key, was, now in moved:
        lines.append(f"  changed {key}: {was} -> {now}")
    for key in added:
        lines.append(f"  added   {key}")
    for key in dropped:
        lines.append(f"  dropped {key}")
    return lines


def record_upstream(version, digest):
    """Write the version and hash into the overlay, leaving the rest alone.

    A line edit rather than a JSON round-trip: the overlay is a file people read,
    and re-serialising it would reflow every comment in it to prove a point
    about formatting that nobody asked for.
    """
    text = OVERLAY.read_text(encoding="utf-8")
    text = re.sub(r'("version":\s*)"[^"]*"', rf'\g<1>"{version}"', text, count=1)
    text = re.sub(r'("sha256":\s*)"[^"]*"', rf'\g<1>"{digest}"', text, count=1)
    OVERLAY.write_text(text, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--design-system", default=None,
        help=f"path to the design-system directory, the one holding "
             f"tokens/tokens.json. May be given as ${ENV_VAR} instead.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="report differences and exit non-zero; change nothing",
    )
    args = parser.parse_args(argv)

    design_system = design_system_path(args.design_system)
    if design_system is None:
        print(
            f"Point --design-system (or ${ENV_VAR}) at a design-system "
            "directory containing tokens/tokens.json.",
            file=sys.stderr,
        )
        return 2

    source = design_system / "tokens" / "tokens.json"
    upstream = json.loads(source.read_text(encoding="utf-8"))
    vendored = json.loads(VENDORED.read_text(encoding="utf-8"))
    overlay = json.loads(OVERLAY.read_text(encoding="utf-8"))

    identical = sha256(source) == sha256(VENDORED)
    recorded = overlay["$upstream"]["sha256"] == sha256(VENDORED)

    if not recorded:
        print(
            f"{OVERLAY.name} records a hash the vendored file does not have — "
            f"somebody edited {VENDORED.name} in place.",
            file=sys.stderr,
        )

    if identical and recorded:
        print(f"up to date with {source} (v{upstream['$meta']['version']})")
        return 0

    lines = report(
        *differences(vendored, upstream),
        upstream["$meta"]["version"],
        vendored["$meta"]["version"],
    )
    print(f"{source} differs from the copy in {VENDORED.name}:")
    print("\n".join(lines) if lines else "  (no token values differ — formatting only)")

    if args.check:
        print("\n--check: nothing written. Re-run without it to take the change.")
        return 1

    shutil.copyfile(source, VENDORED)
    record_upstream(upstream["$meta"]["version"], sha256(VENDORED))
    print(
        f"\ntook {source} -> {VENDORED.relative_to(REPO)} "
        f"(v{upstream['$meta']['version']})\n"
        "Now run the tests: the contrast audit is what says whether a changed "
        "token broke a pairing."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
