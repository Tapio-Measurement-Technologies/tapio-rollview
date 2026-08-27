"""Compile ``translations/*.po`` into the ``.mo`` catalogs gettext reads.

The ``.mo`` files are build output, not source: they are generated from the
``.po`` files and deliberately untracked, because a committed binary catalog
conflicts on every merge that touches translations and cannot be resolved by
hand. Everything that needs them compiles them instead — ``utils.translation``
on import when running from a checkout, and the build workflow before
PyInstaller bundles ``src/locales/``.

Implemented here rather than shelling out to ``msgfmt`` so a plain Python
checkout on Windows needs no gettext tooling installed.
"""

import ast
import struct
import sys
from pathlib import Path

# (po file relative to the repo root, mo file relative to src/)
CATALOGS = (
    ("translations/messages_en.po", "locales/en/LC_MESSAGES/messages.mo"),
    ("translations/messages_ja.po", "locales/ja/LC_MESSAGES/messages.mo"),
)

SRC_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SRC_DIR.parent


def _unquote(po_quoted_text: str) -> str:
    return ast.literal_eval(po_quoted_text)


def parse_po(po_path: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    msgid_parts: list[str] | None = None
    msgstr_parts: list[str] | None = None
    current: str | None = None
    fuzzy = False

    def commit() -> None:
        nonlocal msgid_parts, msgstr_parts, current, fuzzy
        if msgid_parts is None or msgstr_parts is None or fuzzy:
            msgid_parts = None
            msgstr_parts = None
            current = None
            fuzzy = False
            return

        msgid = "".join(msgid_parts)
        msgstr = "".join(msgstr_parts)
        messages[msgid] = msgstr
        msgid_parts = None
        msgstr_parts = None
        current = None
        fuzzy = False

    with po_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\n")

            if line.startswith("#,") and "fuzzy" in line:
                fuzzy = True
                continue

            if not line:
                commit()
                continue

            if line.startswith("#"):
                continue

            if line.startswith("msgid "):
                commit()
                msgid_parts = [_unquote(line[6:])]
                msgstr_parts = []
                current = "msgid"
                continue

            if line.startswith("msgstr "):
                if msgid_parts is None:
                    raise ValueError(f"Found msgstr before msgid in {po_path}")
                msgstr_parts = [_unquote(line[7:])]
                current = "msgstr"
                continue

            if line.startswith('"'):
                if current == "msgid" and msgid_parts is not None:
                    msgid_parts.append(_unquote(line))
                    continue
                if current == "msgstr" and msgstr_parts is not None:
                    msgstr_parts.append(_unquote(line))
                    continue

        commit()

    return messages


def write_mo(messages: dict[str, str], mo_path: Path) -> None:
    keys = sorted(messages.keys())
    ids = b""
    strs = b""
    id_offsets: list[tuple[int, int]] = []
    str_offsets: list[tuple[int, int]] = []

    for key in keys:
        key_bytes = key.encode("utf-8")
        value_bytes = messages[key].encode("utf-8")

        id_offsets.append((len(key_bytes), len(ids)))
        ids += key_bytes + b"\0"

        str_offsets.append((len(value_bytes), len(strs)))
        strs += value_bytes + b"\0"

    count = len(keys)
    header_size = 7 * 4
    orig_table_offset = header_size
    trans_table_offset = orig_table_offset + count * 8
    ids_offset = trans_table_offset + count * 8
    strs_offset = ids_offset + len(ids)

    output = bytearray()
    output.extend(struct.pack("Iiiiiii", 0x950412DE, 0, count, orig_table_offset, trans_table_offset, 0, 0))

    for length, offset in id_offsets:
        output.extend(struct.pack("II", length, ids_offset + offset))

    for length, offset in str_offsets:
        output.extend(struct.pack("II", length, strs_offset + offset))

    output.extend(ids)
    output.extend(strs)

    mo_path.parent.mkdir(parents=True, exist_ok=True)
    mo_path.write_bytes(output)


def compile_one(po_path: Path, mo_path: Path) -> None:
    write_mo(parse_po(po_path), mo_path)


def compile_all(force: bool = True, verbose: bool = False) -> None:
    """Compile every catalog whose ``.mo`` is missing or older than its ``.po``.

    With ``force``, compile regardless of timestamps.
    """
    for po_rel, mo_rel in CATALOGS:
        po_path = REPO_ROOT / po_rel
        mo_path = SRC_DIR / mo_rel
        if not po_path.exists():
            continue
        if not force and mo_path.exists() and mo_path.stat().st_mtime >= po_path.stat().st_mtime:
            continue
        compile_one(po_path, mo_path)
        if verbose:
            print(f"Compiled {po_path} -> {mo_path}")


def ensure_compiled() -> None:
    """Bring the catalogs up to date for a source checkout, best effort.

    A frozen build ships catalogs compiled at build time and has no ``.po``
    files to compile from, so it is skipped. A checkout on read-only media
    falls through to whatever ``.mo`` files are already there — gettext itself
    falls back to the message keys if there are none.
    """
    if getattr(sys, "frozen", False):
        return
    try:
        compile_all(force=False)
    except (OSError, ValueError):
        pass
