import ast
import os
import struct
from pathlib import Path


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


def compile_one(po_rel: str, mo_rel: str) -> None:
    repo_root = Path(__file__).resolve().parent
    po_path = repo_root / po_rel
    mo_path = repo_root / mo_rel
    messages = parse_po(po_path)
    write_mo(messages, mo_path)
    print(f"Compiled {po_path} -> {mo_path}")


def main() -> None:
    compile_one("translations/messages_en.po", "src/locales/en/LC_MESSAGES/messages.mo")
    compile_one("translations/messages_ja.po", "src/locales/ja/LC_MESSAGES/messages.mo")


if __name__ == "__main__":
    main()
