from __future__ import annotations

import argparse
import math
import struct
from dataclasses import dataclass
from pathlib import Path

from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.ttLib import TTCollection, TTFont


TEMPLATE_CMAP_RANGES = (
    range(0x20, 0x41),
    range(0x5B, 0x60),
    range(0x591, 0x5C8),
    range(0x5D0, 0x5EB),
)
CODEPOINTS = [cp for block in TEMPLATE_CMAP_RANGES for cp in block]
assert len(CODEPOINTS) == 120

HEADER_SIZE = 0x98
OFFSET_BASE = 0x90
OFFSET_TABLE_SIZE = 121 * 4
GLYPH_DATA_OFFSET = HEADER_SIZE + OFFSET_TABLE_SIZE
TARGET_EM_UNITS = 32 * 64
HEBREW_LETTERS = set(range(0x5D0, 0x5EB))


class ConversionError(RuntimeError):
    pass


@dataclass
class ConvertedFont:
    source: Path
    output: Path
    family: str
    glyphs_with_outlines: int
    missing_codepoints: list[int]


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def font_name(font: TTFont, name_id: int) -> str:
    name_table = font["name"]
    for platform, encoding, language in ((3, 1, 0x409), (3, 10, 0x409), (1, 0, 0)):
        record = name_table.getName(name_id, platform, encoding, language)
        if record is not None:
            try:
                return record.toUnicode().strip()
            except Exception:
                pass
    for record in name_table.names:
        if record.nameID == name_id:
            try:
                value = record.toUnicode().strip()
                if value:
                    return value
            except Exception:
                pass
    return ""


def expand_outline(font: TTFont, glyph_name: str, scale: float):
    glyph_set = font.getGlyphSet()
    recording = DecomposingRecordingPen(glyph_set)
    glyph_set[glyph_name].draw(recording)

    pen = TTGlyphPen(None)
    destination_pen = pen
    if "glyf" not in font:
        destination_pen = Cu2QuPen(pen, max_err=2.0, reverse_direction=True)
    transformed = TransformPen(destination_pen, (scale, 0, 0, scale, 0, 0))
    recording.replay(transformed)
    return pen.glyph()


def simple_glyph_payload(glyph, glyf_table) -> tuple[int, int, bytes, bytes]:
    contours = glyph.numberOfContours
    if contours <= 0:
        return 0, 0, b"", b""
    if contours > 255:
        raise ConversionError(f"glyph has {contours} contours; maximum is 255")

    if glyf_table is None:
        class StandardGlyfTable:
            extended = False

        glyf_table = StandardGlyfTable()
    raw = glyph.compile(glyf_table, recalcBBoxes=True, optimizeSize=True)
    if len(raw) < 12:
        raise ConversionError("compiled glyph is unexpectedly short")

    raw_contours = struct.unpack_from(">h", raw, 0)[0]
    if raw_contours != contours:
        raise ConversionError("compiled glyph contour count changed")

    cursor = 10
    end_points = list(struct.unpack_from(f">{contours}H", raw, cursor))
    cursor += contours * 2
    point_count = end_points[-1] + 1
    if point_count > 255:
        raise ConversionError(f"glyph has {point_count} points; maximum is 255")

    instruction_length = struct.unpack_from(">H", raw, cursor)[0]
    cursor += 2 + instruction_length
    if cursor > len(raw):
        raise ConversionError("glyph instruction block exceeds its record")

    payload = raw[cursor:]
    endpoints = bytes(end_points)
    return point_count, contours, payload, endpoints


def advance_pixels(font: TTFont, glyph_name: str | None, scale: float, fallback: int = 0) -> int:
    if not glyph_name:
        return fallback
    advance, _lsb = font["hmtx"][glyph_name]
    value = round_half_up((advance * scale) / 64.0)
    return max(0, min(255, value))


def empty_record(advance: int) -> bytes:
    return bytes((8, advance, 3, 0, 0))


def glyph_record(font: TTFont, glyph_name: str, scale: float) -> bytes:
    advance = advance_pixels(font, glyph_name, scale)
    glyph = expand_outline(font, glyph_name, scale)
    points, contours, payload, endpoints = simple_glyph_payload(glyph, font.get("glyf"))
    if not points or not contours:
        return empty_record(advance)
    return bytes((8, advance, 7, points, contours)) + payload + endpoints


def validate_record(record: bytes) -> None:
    if len(record) < 5 or record[0] != 8 or record[2] not in (3, 7):
        raise ConversionError("invalid glyph record header")
    point_count = record[3]
    contour_count = record[4]
    if not point_count and not contour_count:
        if len(record) != 5:
            raise ConversionError("empty glyph record contains extra data")
        return
    if not point_count or not contour_count or record[2] != 7:
        raise ConversionError("inconsistent glyph record counts")

    data = record[5:]
    flags: list[int] = []
    cursor = 0
    while len(flags) < point_count:
        if cursor >= len(data):
            raise ConversionError("glyph flag stream is truncated")
        flag = data[cursor]
        cursor += 1
        flags.append(flag)
        if flag & 0x08:
            if cursor >= len(data):
                raise ConversionError("glyph repeat flag is truncated")
            repeat = data[cursor]
            cursor += 1
            flags.extend([flag] * repeat)
    if len(flags) != point_count:
        raise ConversionError("glyph flag stream exceeds point count")

    for axis_short, axis_same in ((0x02, 0x10), (0x04, 0x20)):
        for flag in flags:
            width = 1 if flag & axis_short else (0 if flag & axis_same else 2)
            cursor += width
    cursor += contour_count
    if cursor != len(data):
        raise ConversionError("glyph coordinate stream length mismatch")

    endpoints = data[-contour_count:]
    if endpoints[-1] != point_count - 1 or any(a >= b for a, b in zip(endpoints, endpoints[1:])):
        raise ConversionError("invalid contour endpoints")


def build_lib(template: bytes, records: list[bytes]) -> bytes:
    if len(template) < HEADER_SIZE or template[:4] != b"sfon":
        raise ConversionError("template is not a supported SFON library")
    if len(records) != 121:
        raise ConversionError("SFON library must contain exactly 121 glyph records")
    for record in records:
        validate_record(record)

    prefix = bytearray(template[:HEADER_SIZE])
    offsets = bytearray()
    cursor = GLYPH_DATA_OFFSET
    for record in records:
        offsets.extend(struct.pack(">I", cursor - OFFSET_BASE))
        cursor += len(record)
    return bytes(prefix) + bytes(offsets) + b"".join(records)


def validate_lib(blob: bytes) -> None:
    if blob[:4] != b"sfon":
        raise ConversionError("output magic is missing")
    offsets = [
        struct.unpack_from(">I", blob, HEADER_SIZE + i * 4)[0] + OFFSET_BASE
        for i in range(121)
    ]
    if offsets[0] != GLYPH_DATA_OFFSET or offsets != sorted(offsets):
        raise ConversionError("glyph offset table is invalid")
    for index, start in enumerate(offsets):
        end = offsets[index + 1] if index + 1 < len(offsets) else len(blob)
        if start > end or end > len(blob):
            raise ConversionError("glyph offset is outside the file")
        validate_record(blob[start:end])


def convert_font(source: Path, destination: Path, template: bytes, face_index: int = 0) -> ConvertedFont:
    font = TTFont(source, lazy=False, fontNumber=face_index)
    try:
        if "hmtx" not in font or not any(table in font for table in ("glyf", "CFF ", "CFF2")):
            raise ConversionError("font does not contain supported outlines")
        cmap = font.getBestCmap() or {}
        missing_letters = sorted(cp for cp in HEBREW_LETTERS if cp not in cmap)
        if missing_letters:
            raise ConversionError("font does not contain the full Hebrew alphabet")

        units_per_em = font["head"].unitsPerEm
        if not units_per_em:
            raise ConversionError("font has an invalid units-per-em value")
        scale = TARGET_EM_UNITS / units_per_em

        notdef_name = ".notdef" if ".notdef" in font.getGlyphOrder() else None
        records = [empty_record(advance_pixels(font, notdef_name, scale, fallback=16))]
        missing: list[int] = []
        outlined = 0
        for cp in CODEPOINTS:
            glyph_name = cmap.get(cp)
            if not glyph_name:
                missing.append(cp)
                records.append(empty_record(0))
                continue
            try:
                record = glyph_record(font, glyph_name, scale)
            except ConversionError:
                if cp in HEBREW_LETTERS:
                    raise
                missing.append(cp)
                records.append(empty_record(advance_pixels(font, glyph_name, scale)))
                continue
            if record[2] == 7:
                outlined += 1
            records.append(record)

        blob = build_lib(template, records)
        validate_lib(blob)
        destination.write_bytes(blob)
        return ConvertedFont(
            source=source,
            output=destination,
            family=font_name(font, 1) or source.stem,
            glyphs_with_outlines=outlined,
            missing_codepoints=missing,
        )
    finally:
        font.close()


def unique_destination(folder: Path, source: Path, used: set[str]) -> Path:
    base = source.stem.strip().rstrip(".") or "font"
    candidate = base
    suffix = 2
    while candidate.casefold() in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate.casefold())
    return folder / f"{candidate}.lib"


def safe_stem(value: str) -> str:
    invalid = '<>:"/\\|?*'
    result = "".join("-" if char in invalid else char for char in value).strip().rstrip(".")
    return result or "font"


def collection_faces(path: Path) -> list[tuple[int, str]]:
    collection = TTCollection(path, lazy=True)
    try:
        faces: list[tuple[int, str]] = []
        for index, font in enumerate(collection.fonts):
            family = font_name(font, 1) or path.stem
            style = font_name(font, 2)
            label = safe_stem(f"{family}-{style}" if style else family)
            faces.append((index, label))
        return faces
    finally:
        collection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Hebrew TrueType fonts to KING G7 SFON .lib files")
    parser.add_argument("source", type=Path, help="TTF file or folder containing TTF files")
    parser.add_argument("output", type=Path, help="destination folder")
    parser.add_argument("--template", type=Path, required=True, help="known-good KING G7 .lib file")
    args = parser.parse_args()

    source: Path = args.source
    output: Path = args.output
    template = args.template.read_bytes()
    output.mkdir(parents=True, exist_ok=True)

    extensions = {".ttf", ".ttc", ".otf"}
    files = [source] if source.is_file() else sorted(
        (path for path in source.rglob("*") if path.suffix.lower() in extensions),
        key=lambda p: str(p).casefold(),
    )
    used: set[str] = {path.stem.casefold() for path in output.glob("*.lib")}
    converted: list[ConvertedFont] = []
    skipped: list[tuple[Path, str]] = []
    for path in files:
        if path.suffix.lower() == ".ttc":
            try:
                faces = collection_faces(path)
            except Exception as exc:
                skipped.append((path, str(exc)))
                print(f"SKIP\t{path.name}\t{exc}")
                continue
        else:
            faces = [(0, path.stem)]

        for face_index, face_label in faces:
            destination = unique_destination(output, path.with_name(f"{face_label}{path.suffix}"), used)
            face_source = path if len(faces) == 1 else Path(f"{path}#{face_index}")
            try:
                result = convert_font(path, destination, template, face_index=face_index)
                converted.append(result)
                print(f"OK\t{face_source.name}\t{destination.name}\t{result.glyphs_with_outlines} outlines\t{len(result.missing_codepoints)} missing")
            except Exception as exc:
                if destination.exists():
                    destination.unlink()
                skipped.append((face_source, str(exc)))
                print(f"SKIP\t{face_source.name}\t{exc}")

    print(f"SUMMARY\tconverted={len(converted)}\tskipped={len(skipped)}\ttotal={len(files)}")
    return 0 if converted else 1


if __name__ == "__main__":
    raise SystemExit(main())

