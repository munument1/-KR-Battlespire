"""Conservative Battlespire resource inspector and translation staging tools.

Requires only Python 3.10+. Never writes a game's input files. No Korean runtime
encoding is known yet, so writing text is restricted to printable ASCII.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path


class FormatError(ValueError):
    """Refuse unrecognized or unsafe file layouts."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


@dataclass(frozen=True)
class Entry:
    index: int
    name: str
    offset: int
    size: int
    compression: int


class BSA:
    """XnGine BSA: named records 0x100, numbered 0x200, directory at EOF."""

    def __init__(self, data: bytes):
        if len(data) < 4:
            raise FormatError("BSA header truncated")
        count, kind = struct.unpack_from("<HH", data)
        if kind == 0x100:
            pos, fmt, length = 4, "<12sHI", 18
        elif kind == 0x200:
            pos, fmt, length = 4, "<HHI", 8
        else:
            pos, fmt, length = 2, "<12sHI", 18  # older legacy BSA
        table_start = len(data) - count * length
        if count == 0 or table_start < pos:
            raise FormatError("Invalid BSA directory")
        self.entries = []
        self.data = data
        for i in range(count):
            value, compressed, size = struct.unpack_from(fmt, data, table_start + i * length)
            if isinstance(value, bytes):
                name = value.split(b"\x00", 1)[0].decode("ascii")
                if not re.fullmatch(r"[A-Za-z0-9_!.#$~-]{1,8}(?:\.[A-Za-z0-9_]{1,3})?", name):
                    raise FormatError(f"Unsafe member name: {name!r}")
            else:
                name = f"{value:05d}_{i:06d}.bin"
            if compressed not in (0, 0x100):
                raise FormatError(f"Unsupported BSA compression flag: {compressed:#x}")
            if pos + size > table_start:
                raise FormatError(f"BSA member {name} overlaps directory")
            self.entries.append(Entry(i, name, pos, size, compressed))
            pos += size
        if pos != table_start:
            raise FormatError(f"BSA directory gap: {pos} != {table_start}")

    @classmethod
    def read(cls, path: Path) -> BSA:
        return cls(path.read_bytes())

    def extract(self, entry: Entry) -> bytes:
        raw = self.data[entry.offset : entry.offset + entry.size]
        return lzss(raw) if entry.compression else raw


def lzss(data: bytes, limit: int = 32 * 1024 * 1024) -> bytes:
    """ariscop's Battlespire LZSS, LSB flags and 4096-byte sliding window."""
    window = bytearray(b" " * 4078 + b"\x00" * 18)
    out = bytearray()
    cursor = 4078
    pos = 0

    def emit(byte: int) -> None:
        nonlocal cursor
        if len(out) >= limit:
            raise FormatError("LZSS output size limit exceeded")
        out.append(byte)
        window[cursor] = byte
        cursor = (cursor + 1) & 0xFFF

    while pos < len(data):
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if pos >= len(data):
                break
            if flags & (1 << bit):
                emit(data[pos])
                pos += 1
            else:
                if pos + 2 > len(data):
                    raise FormatError("Truncated LZSS backreference")
                low, high = data[pos : pos + 2]
                pos += 2
                source = low | ((high & 0xF0) << 4)
                for shift in range((high & 0x0F) + 3):
                    emit(window[(source + shift) & 0xFFF])
    return bytes(out)


@dataclass(frozen=True)
class RSCRecord:
    index: int
    resource_id: int
    start: int
    content: bytes


class RSC:
    """TEXT.RSC directory: u32 table_end, (u32 offset,u16 id) records; FE end."""

    def __init__(self, data: bytes):
        if len(data) < 12:
            raise FormatError("RSC truncated")
        table_end = struct.unpack_from("<I", data)[0]
        if table_end < 12 or table_end > len(data) or (table_end - 6) % 6:
            raise FormatError("Unexpected RSC table header")
        count = (table_end - 6) // 6
        directory = [struct.unpack_from("<IH", data, 4 + 6 * i) for i in range(count)]
        offsets = [v[0] for v in directory]
        if not all(table_end <= v < len(data) for v in offsets):
            raise FormatError("RSC offset outside data")
        if offsets != sorted(offsets):
            raise FormatError("RSC offsets not nondecreasing")
        if directory[-1][1] != 0xFFFF:
            raise FormatError("RSC final sentinel id not found")
        self.data = data
        self.table_end = table_end
        self.records = [RSCRecord(i, record_id, start,
                                  data[start : offsets[i + 1] if i + 1 < count else len(data)])
                        for i, (start, record_id) in enumerate(directory)]

    @classmethod
    def read(cls, path: Path) -> RSC:
        return cls(path.read_bytes())

    def text(self, record: RSCRecord) -> bytes:
        # Keep the entire unknown suffix including FE, because some rows have
        # multiple delimiters and/or binary control tokens.
        if not record.content:
            return b""
        mark = record.content.find(b"\xfe")
        if mark < 0:
            raise FormatError(f"RSC resource {record.resource_id} has no FE delimiter")
        return record.content[:mark]

    def replace(self, changes: dict[int, bytes]) -> bytes:
        # Resource IDs, control bytes and all untouched suffixes remain intact.
        valid = {r.index for r in self.records[:-1]}
        if not changes.keys() <= valid:
            raise FormatError("Attempt to alter nonexistent resource/sentinel")
        output = bytearray(self.data[: self.records[0].start])
        for record in self.records:
            struct.pack_into("<I", output, 4 + record.index * 6, len(output))
            if record.index in changes:
                source = self.text(record)
                replacement = changes[record.index]
                if len(replacement) > len(source):
                    raise FormatError("Replacement exceeds existing RSC byte length")
                if not all(32 <= b < 127 for b in replacement):
                    raise FormatError("Only printable ASCII is supported for test writes")
                output.extend(replacement)
                output.extend(record.content[len(source) :])
            else:
                output.extend(record.content)
        return bytes(output)


class FNT:
    """Observed Battlespire FNT format: N, reserved, N*(u16 w,u16 h), N*u32
    absolute offsets, then N RGB555 little-endian pixel blocks.
    """

    def __init__(self, data: bytes, *, max_count: int = 1024):
        if len(data) < 8:
            raise FormatError("FNT header truncated")
        self.data = data
        self.count, self.reserved = struct.unpack_from("<HH", data)
        self.bitmap_start = 4 + self.count * 8
        if not (1 <= self.count <= min(max_count, 65535)) or len(data) < self.bitmap_start:
            raise FormatError("FNT count or tables invalid")
        self.dimensions = [struct.unpack_from("<HH", data, 4 + 4 * i) for i in range(self.count)]
        self.offsets = [struct.unpack_from("<I", data, 4 + 4 * self.count + 4 * i)[0]
                        for i in range(self.count)]
        for i, ((w, h), start) in enumerate(zip(self.dimensions, self.offsets)):
            # Unallocated glyph slots use dimensions (1,1) and an EOF pointer.
            placeholder = start == len(data) and w == 1 and h == 1
            if start < self.bitmap_start or start > len(data) or (not placeholder and start + w * h * 2 > len(data)):
                raise FormatError(f"FNT glyph #{i} offset/dimensions invalid")
            if i and start < self.offsets[i - 1]:
                raise FormatError("FNT offsets unordered")
            if i + 1 < self.count and not placeholder and start + w * h * 2 > self.offsets[i + 1]:
                raise FormatError(f"FNT glyph #{i} overlaps next glyph")

    @classmethod
    def read(cls, path: Path) -> FNT:
        return cls(path.read_bytes())

    def pixels(self, index: int) -> tuple[int, int, tuple[int, ...]]:
        w, h = self.dimensions[index]
        off = self.offsets[index]
        if off == len(self.data):
            raise FormatError("Unallocated glyph slot")
        return w, h, struct.unpack_from("<" + str(w * h) + "H", self.data, off)

    def paint(self, index: int, pixels: list[int]) -> bytes:
        w, h = self.dimensions[index]
        if self.offsets[index] == len(self.data):
            raise FormatError("Cannot paint unallocated glyph without rebuilding FNT")
        if len(pixels) != w * h or any(not 0 <= c <= 0xFFFF for c in pixels):
            raise FormatError("Replacement glyph pixels/dimensions mismatch")
        out = bytearray(self.data)
        struct.pack_into("<" + str(w * h) + "H", out, self.offsets[index], *pixels)
        return bytes(out)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    if len(rgba) != width * height * 4:
        raise FormatError("PNG pixels/dimensions mismatch")

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))

    rows = b"".join(b"\x00" + rgba[y * width * 4 : (y + 1) * width * 4] for y in range(height))
    write_new(path, b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
              + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def font_png(font: FNT, index: int, path: Path, scale: int = 4) -> None:
    w, h, pixels = font.pixels(index)
    if not w or not h:
        raise FormatError("Empty glyph")
    out = bytearray()
    for y in range(h):
        line = bytearray()
        for x in range(w):
            px = pixels[y * w + x]
            r, g, b = (px >> 10) & 31, (px >> 5) & 31, px & 31
            line.extend((r * 255 // 31, g * 255 // 31, b * 255 // 31, 255))
        expanded = b"".join(line[x * 4 : x * 4 + 4] * scale for x in range(w))
        out.extend(expanded * scale)
    write_png(path, w * scale, h * scale, bytes(out))


def font_poc(font: FNT, codes: str, hangul: str, ttf: Path) -> bytes:
    """Replace two or more *existing* ASCII bitmap cells with Korean shapes.

    For a controlled glyph-routing test only. Input text remains ASCII codes;
    real Unicode/Korean encoding is not added to the game engine.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise FormatError("font-poc requires optional dependency Pillow") from exc
    if len(codes) != len(hangul) or not codes or len(set(codes)) != len(codes):
        raise FormatError("codes and hangul must have equal nonzero length with unique codes")
    if not all("가" <= char <= "힣" for char in hangul):
        raise FormatError("Test text must use precomposed Hangul syllables")
    output = font.data
    for code, char in zip(codes, hangul):
        index = ord(code) - 33
        if not 0 <= index < font.count or font.offsets[index] >= len(font.data):
            raise FormatError(f"No allocated FNT glyph for {code!r} (index {index})")
        w, h, _ = font.pixels(index)
        selected = None
        for fontsize in range(min(w, h) + 8, 3, -1):
            face = ImageFont.truetype(str(ttf), fontsize)
            left, top, right, bottom = face.getbbox(char)
            if 0 < right - left <= w and 0 < bottom - top <= h:
                selected = (face, left, top, right - left, bottom - top)
                break
        if selected is None:
            raise FormatError(f"Cannot fit {char} into {w}x{h} glyph slot")
        face, left, top, width, height = selected
        image = Image.new("L", (w, h))
        draw = ImageDraw.Draw(image)
        draw.text(((w - width) // 2 - left, (h - height) // 2 - top), char, font=face, fill=255)
        mask_pixels = list(image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata())
        if not any(mask_pixels):
            raise FormatError(f"TTF produced empty glyph for {char}")
        output = FNT(output).paint(index, [0x7FFF if px > 75 else 0 for px in mask_pixels])
    return output


FIELDS = ["filename", "entry", "line", "column", "source_sha256", "source", "safe", "max_bytes", "translation"]
RSC_FIELDS = ["index", "resource_id", "source_sha256", "source", "safe", "max_bytes", "translation"]


def safe_text(raw: bytes) -> bool:
    """Only simple plain-English fields, with no game control tokens, are editable."""
    return (len(raw) >= 3 and all(32 <= x < 127 for x in raw)
            and bool(re.fullmatch(rb"[A-Za-z0-9 ,.!?'\"():;\-/]+", raw))
            and bool(re.search(rb"[A-Za-z]{3}", raw)))


def txt_lines(data: bytes) -> list[bytes]:
    return data.split(b"\n")


def txt_export(archive: BSA, path: Path) -> tuple[int, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    safe = 0
    with path.open("x", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for entry in archive.entries:
            if not entry.name.upper().endswith(".TXT"):
                continue
            for linenum, line in enumerate(txt_lines(archive.extract(entry))):
                for col, value in enumerate(line.split(b"\t")):
                    body = value.rstrip(b"\r")
                    candidate = safe_text(body)
                    if not value.strip():
                        continue
                    writer.writerow(dict(filename=entry.name, entry=entry.index, line=linenum,
                                         column=col, source_sha256=digest(value),
                                         source=body.decode("cp1252", "replace"),
                                         safe=int(candidate), max_bytes=len(body), translation=""))
                    total += 1
                    safe += candidate
    return total, safe


def read_csv(path: Path, schema: list[str]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != schema:
            raise FormatError(f"CSV headers differ from expected schema: {schema}")
        return list(reader)


def ascii_replacement(row: dict[str, str], source: bytes) -> bytes | None:
    # TXT.BSA uses CR CR LF on many lines. Preserve both CR bytes verbatim.
    body = source.rstrip(b"\r")
    suffix = source[len(body) :]
    if row["source_sha256"] != digest(source):
        raise FormatError("Original source SHA-256 changed")
    if int(row["max_bytes"]) != len(body) or int(row["safe"]) != int(safe_text(body)):
        raise FormatError("Source metadata changed or source is unsafe")
    if row["source"] != body.decode("cp1252", "replace"):
        raise FormatError("CSV source text has been edited")
    translation = row["translation"]
    if not translation:
        return None
    if not safe_text(body):
        raise FormatError("Translation requested for non-plain-text field")
    try:
        encoded = translation.encode("ascii")
    except UnicodeEncodeError as exc:
        raise FormatError("Korean/extended encoding is not implemented; ASCII PoC only") from exc
    if len(encoded) > len(body) or not all(32 <= x < 127 for x in encoded):
        raise FormatError("Translation exceeds byte budget or introduces control syntax")
    return encoded + suffix


def txt_apply(archive: BSA, csv_path: Path, dest: Path, *, dry_run: bool = False) -> dict[str, int]:
    entries = {e.name: e for e in archive.entries if e.name.upper().endswith(".TXT")}
    incoming = read_csv(csv_path, FIELDS)
    changes: dict[tuple[str, int, int], dict[str, str]] = {}
    for row in incoming:
        filename = row["filename"]
        if filename not in entries or int(row["entry"]) != entries[filename].index:
            raise FormatError(f"Unknown or mismatched archive member {filename}")
        key = filename, int(row["line"]), int(row["column"])
        if key in changes:
            raise FormatError(f"Duplicate CSV field {key}")
        changes[key] = row
    files: dict[str, bytes] = {}
    edited = 0
    for name, entry in entries.items():
        raw = archive.extract(entry)
        lines = txt_lines(raw)
        touched = False
        for line_no, line in enumerate(lines):
            cells = line.split(b"\t")
            for col, cell in enumerate(cells):
                row = changes.pop((name, line_no, col), None)
                if row is None:
                    continue
                if not cell.strip():
                    raise FormatError(f"CSV references empty field {name}:{line_no}:{col}")
                replacement = ascii_replacement(row, cell)
                if replacement is not None:
                    # TXT files frequently contain control flow, object IDs,
                    # dialogue routing and NPC state keys. Until a semantic
                    # schema is written, restrict modifications to book
                    # members and leave all control-table files untouched.
                    if not name.upper().startswith(("BOOK", "BK")):
                        raise FormatError(f"Dialogue/metadata schema not verified: {name}")
                    cells[col] = replacement
                    edited += 1
                    touched = True
            lines[line_no] = b"\t".join(cells)
        if touched:
            files[name] = b"\n".join(lines)
    if changes:
        raise FormatError(f"CSV has unknown line/column keys: {list(changes)[:3]}")
    if not dry_run:
        if dest.resolve() in (Path.cwd().resolve(),):
            raise FormatError("Please specify a dedicated output directory")
        if any((dest / name).exists() for name in files):
            raise FormatError("Output contains files that would be overwritten")
        for name, contents in files.items():
            write_new(dest / name, contents)
    return {"edited_fields": edited, "loose_files": len(files)}


def rsc_export(resource: RSC, output: Path) -> tuple[int, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    safe = 0
    with output.open("x", encoding="utf-8-sig", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=RSC_FIELDS)
        writer.writeheader()
        for rec in resource.records[:-1]:
            cell = resource.text(rec)
            ok = safe_text(cell)
            safe += ok
            writer.writerow(dict(index=rec.index, resource_id=rec.resource_id,
                                 source_sha256=digest(cell), source=cell.decode("cp1252", "replace"),
                                 safe=int(ok), max_bytes=len(cell), translation=""))
    return len(resource.records) - 1, safe


def rsc_apply(resource: RSC, csv_path: Path, output: Path, *, dry_run: bool = False) -> dict[str, int]:
    rows = read_csv(csv_path, RSC_FIELDS)
    edits: dict[int, bytes] = {}
    seen = set()
    for row in rows:
        index = int(row["index"])
        if index in seen or index < 0 or index >= len(resource.records) - 1:
            raise FormatError(f"Invalid/duplicate RSC index {index}")
        seen.add(index)
        rec = resource.records[index]
        if int(row["resource_id"]) != rec.resource_id:
            raise FormatError("RSC ID does not match")
        replacement = ascii_replacement(row, resource.text(rec))
        if replacement is not None:
            edits[index] = replacement
    if not dry_run and edits:
        replacement = resource.replace(edits)
        RSC(replacement)  # Verify rebuilt directory before writing.
        write_new(output, replacement)
    return {"edited_resources": len(edits), "source_resources": len(resource.records) - 1}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("bsa-list", "bsa-extract", "txt-export", "txt-validate", "txt-apply",
                 "rsc-info", "rsc-export", "rsc-validate", "rsc-apply", "font-info", "font-png", "font-poc"):
        task = sub.add_parser(name)
        task.add_argument("source", type=Path)
        if name in ("txt-export", "txt-validate", "txt-apply", "rsc-export", "rsc-validate", "rsc-apply"):
            task.add_argument("--csv", required=True, type=Path)
        if name in ("txt-apply", "rsc-apply", "bsa-extract", "font-png", "font-poc"):
            task.add_argument("--output", required=True, type=Path)
        if name == "bsa-extract":
            task.add_argument("--member", help="Single exact member name; default extracts all")
        if name == "font-png":
            task.add_argument("--index", type=int, required=True)
        if name == "font-poc":
            task.add_argument("--codes", default="AB", help="Existing ASCII glyph codes to repurpose")
            task.add_argument("--hangul", default="가나", help="Same number of Hangul syllables")
            task.add_argument("--ttf", type=Path, required=True, help="Installed Korean TTF font path")
    args = p.parse_args()
    try:
        if args.command in ("bsa-extract", "txt-apply", "rsc-apply", "font-poc"):
            destination = args.output.resolve()
            source_folder = args.source.resolve().parent
            if destination == source_folder or source_folder in destination.parents:
                raise FormatError("Refusing output inside the source game data directory")
        if args.command.startswith(("bsa-", "txt-")):
            arc = BSA.read(args.source)
        if args.command == "bsa-list":
            print(json.dumps([e.__dict__ for e in arc.entries], indent=2))
        elif args.command == "bsa-extract":
            chosen = [e for e in arc.entries if not args.member or e.name == args.member]
            if not chosen:
                raise FormatError("BSA member not found")
            for entry in chosen:
                write_new(args.output / entry.name, arc.extract(entry))
            print(json.dumps({"extracted": len(chosen)}))
        elif args.command == "txt-export":
            print(json.dumps(dict(zip(("fields", "safe_fields"), txt_export(arc, args.csv)))))
        elif args.command in ("txt-apply", "txt-validate"):
            print(json.dumps(txt_apply(arc, args.csv, args.output if args.command == "txt-apply" else Path("_unused"),
                                       dry_run=args.command == "txt-validate")))
        elif args.command.startswith("rsc-"):
            resource = RSC.read(args.source)
            if args.command == "rsc-info":
                print(json.dumps({"table_end": resource.table_end, "count": len(resource.records) - 1,
                                  "sentinel": resource.records[-1].resource_id, "sha256": digest(resource.data)}))
            elif args.command == "rsc-export":
                print(json.dumps(dict(zip(("resources", "safe_resources"), rsc_export(resource, args.csv)))))
            else:
                print(json.dumps(rsc_apply(resource, args.csv, args.output if args.command == "rsc-apply" else Path("_unused"),
                                           dry_run=args.command == "rsc-validate")))
        elif args.command.startswith("font-"):
            font = FNT.read(args.source)
            if args.command == "font-info":
                print(json.dumps({"glyphs": font.count, "reserved": font.reserved, "bytes": len(font.data),
                                  "bitmap_start": font.bitmap_start, "last_offset": font.offsets[-1],
                                  "sha256": digest(font.data)}))
            elif args.command == "font-png":
                font_png(font, args.index, args.output)
                print(json.dumps({"glyph_index": args.index, "output": str(args.output)}))
            else:
                staged = font_poc(font, args.codes, args.hangul, args.ttf)
                FNT(staged)
                write_new(args.output, staged)
                print(json.dumps({"codes": args.codes, "hangul": args.hangul,
                                  "bytes_identical": len(font.data) == len(staged),
                                  "output": str(args.output)}, ensure_ascii=False))
    except (FormatError, FileExistsError) as exc:
        p.exit(2, f"ERROR: {exc}\n")


if __name__ == "__main__":
    main()
