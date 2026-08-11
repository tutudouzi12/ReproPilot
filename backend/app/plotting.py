from __future__ import annotations

import ast
import base64
import binascii
import hashlib
import json
import math
import struct
import zlib
from typing import Any

from pydantic import BaseModel, Field


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PLOT_WIDTH = 960
PLOT_HEIGHT = 540
MAX_PNG_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 1024 * 1024
MAX_METRICS = 12
PLOT_SOURCE_KEYS = (
    "execution_result",
    "run_metrics",
    "rerun_metrics",
    "benchmark_metrics",
    "benchmark_run_metrics",
    "comparison_report",
)


class PlotMetric(BaseModel):
    id: str
    key: str
    value: float


class PlotManifest(BaseModel):
    version: str = "plot.artifact/v1"
    status: str = "verified"
    renderer: str = "deterministic_stdlib_png"
    mime_type: str = "image/png"
    width: int
    height: int
    byte_size: int
    sha256: str
    source_artifacts: list[str] = Field(default_factory=list)
    source_sha256: dict[str, str] = Field(default_factory=dict)
    metrics: list[PlotMetric] = Field(default_factory=list)


class PlotArtifact(BaseModel):
    image_base64: str
    manifest: PlotManifest


def render_metric_plot(inputs: dict[str, Any]) -> PlotArtifact:
    metrics: list[tuple[str, float]] = []
    sources: list[str] = []
    source_hashes: dict[str, str] = {}
    for artifact_key in PLOT_SOURCE_KEYS:
        if artifact_key not in inputs or inputs[artifact_key] in (None, "", [], {}):
            continue
        raw = inputs[artifact_key]
        if contains_unverified_demo(raw):
            raise ValueError(f"unverified demo artifact cannot be plotted: {artifact_key}")
        payload = _parse_structured(raw, artifact_key)
        candidates = _metric_candidates(artifact_key, payload)
        before = len(metrics)
        for candidate_name, candidate in candidates:
            _collect_metrics(candidate, f"{artifact_key}{candidate_name}", metrics, MAX_METRICS - len(metrics))
            if len(metrics) >= MAX_METRICS:
                break
        if len(metrics) > before:
            sources.append(artifact_key)
            source_hashes[artifact_key] = hashlib.sha256(_canonical_source(raw)).hexdigest()
        if len(metrics) >= MAX_METRICS:
            break
    if not metrics:
        raise ValueError("plot requires at least one finite numeric metric from verified execution artifacts")

    png = _render_png(metrics)
    width, height = validate_png(png)
    digest = hashlib.sha256(png).hexdigest()
    manifest = PlotManifest(
        width=width,
        height=height,
        byte_size=len(png),
        sha256=digest,
        source_artifacts=sources,
        source_sha256=source_hashes,
        metrics=[PlotMetric(id=f"M{index}", key=key, value=value) for index, (key, value) in enumerate(metrics, 1)],
    )
    return PlotArtifact(image_base64=base64.b64encode(png).decode("ascii"), manifest=manifest)


def validate_plot_base64(value: Any) -> tuple[int, int, str]:
    if not isinstance(value, str) or not value:
        raise ValueError("plot image must be non-empty base64")
    if len(value) > ((MAX_PNG_BYTES + 2) // 3) * 4 + 4:
        raise ValueError("plot image exceeds encoded size limit")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("plot image is not valid base64") from exc
    width, height = validate_png(raw)
    return width, height, hashlib.sha256(raw).hexdigest()


def validate_png(raw: bytes) -> tuple[int, int]:
    if len(raw) > MAX_PNG_BYTES:
        raise ValueError("plot PNG exceeds size limit")
    if len(raw) < 33 or not raw.startswith(PNG_SIGNATURE):
        raise ValueError("plot image is not a PNG")
    offset = len(PNG_SIGNATURE)
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("plot PNG contains a truncated chunk")
        length = struct.unpack(">I", raw[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError("plot PNG chunk exceeds the image boundary")
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:offset + 8 + length]
        claimed_crc = struct.unpack(">I", raw[offset + 8 + length:end])[0]
        if binascii.crc32(kind + data) & 0xFFFFFFFF != claimed_crc:
            raise ValueError("plot PNG chunk checksum is invalid")
        if kind not in {b"IHDR", b"IDAT", b"IEND"}:
            raise ValueError("plot PNG contains a chunk outside the deterministic contract")
        chunks.append((kind, data))
        offset = end
        if kind == b"IEND":
            if length != 0 or offset != len(raw):
                raise ValueError("plot PNG has an invalid terminal chunk")
            break
    if not chunks or chunks[0][0] != b"IHDR" or len(chunks[0][1]) != 13:
        raise ValueError("plot PNG has an invalid IHDR")
    if chunks[-1][0] != b"IEND" or not any(kind == b"IDAT" for kind, _ in chunks):
        raise ValueError("plot PNG is missing image data or its terminal chunk")
    if sum(kind == b"IHDR" for kind, _ in chunks) != 1:
        raise ValueError("plot PNG contains multiple IHDR chunks")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunks[0][1])
    if not (64 <= width <= 4096 and 64 <= height <= 4096):
        raise ValueError("plot PNG dimensions are outside the allowed range")
    if (bit_depth, color_type, compression, filtering, interlace) != (8, 2, 0, 0, 0):
        raise ValueError("plot PNG format is not the deterministic RGB contract")
    compressed = b"".join(data for kind, data in chunks if kind == b"IDAT")
    expected_size = height * (1 + width * 3)
    try:
        decompressor = zlib.decompressobj()
        pixels = decompressor.decompress(compressed, expected_size + 1)
        pixels += decompressor.flush(expected_size + 1 - len(pixels))
    except zlib.error as exc:
        raise ValueError("plot PNG image data is not valid zlib content") from exc
    if not decompressor.eof or decompressor.unused_data or decompressor.unconsumed_tail or len(pixels) != expected_size:
        raise ValueError("plot PNG decompressed size does not match its dimensions")
    if any(pixels[row * (1 + width * 3)] != 0 for row in range(height)):
        raise ValueError("plot PNG scanline filter is outside the deterministic contract")
    return width, height


def contains_unverified_demo(value: Any) -> bool:
    if value == "offline-runtime":
        return True
    if isinstance(value, str):
        if "OFFLINE_DEMO_UNVERIFIED" in value or "unverified_demo" in value:
            return True
        try:
            parsed = json.loads(value, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError, TypeError):
            return False
        return contains_unverified_demo(parsed)
    if isinstance(value, dict):
        if value.get("evidence_status") == "unverified_demo":
            return True
        return any(contains_unverified_demo(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_unverified_demo(item) for item in value)
    return False


def _metric_candidates(artifact_key: str, payload: Any) -> list[tuple[str, Any]]:
    if artifact_key == "execution_result":
        if not isinstance(payload, dict):
            raise ValueError("execution_result must be a structured execution record")
        if payload.get("executed") is False:
            raise ValueError("execution_result was not executed")
        exit_code = payload.get("exit_code")
        if exit_code is not None and exit_code != 0:
            raise ValueError("execution_result did not complete successfully")
        candidates: list[tuple[str, Any]] = []
        if payload.get("metrics") not in (None, "", [], {}):
            candidates.append((".metrics", _parse_nested(payload["metrics"], "execution_result.metrics")))
        for key in ("stdout", "result"):
            if payload.get(key) not in (None, "", [], {}):
                candidates.append((f".{key}", _parse_nested(payload[key], f"execution_result.{key}")))
        return candidates
    if artifact_key == "comparison_report":
        if not isinstance(payload, dict) or payload.get("metrics") in (None, "", [], {}):
            raise ValueError("comparison_report does not contain measured metrics")
        return [(".metrics", _parse_nested(payload["metrics"], "comparison_report.metrics"))]
    return [("", payload)]


def _collect_metrics(value: Any, path: str, output: list[tuple[str, float]], remaining: int) -> None:
    if remaining <= 0:
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"non-finite metric rejected at {path}")
        output.append((path, numeric))
        return
    if isinstance(value, dict):
        start = len(output)
        for key in sorted(value, key=str):
            _collect_metrics(value[key], f"{path}.{str(key)[:80]}", output, remaining - (len(output) - start))
            if len(output) - start >= remaining:
                break
        return
    if isinstance(value, (list, tuple)):
        start = len(output)
        for index, item in enumerate(value[:MAX_METRICS]):
            _collect_metrics(item, f"{path}[{index}]", output, remaining - (len(output) - start))
            if len(output) - start >= remaining:
                break


def _parse_structured(value: Any, label: str) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return value
    return _parse_nested(value, label)


def _parse_nested(value: Any, label: str) -> Any:
    if isinstance(value, (dict, list, tuple, int, float)) and not isinstance(value, bool):
        return value
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is empty")
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError(f"{label} exceeds the structured input limit")
    candidates = [text, *[line.strip() for line in reversed(text.splitlines()) if line.strip()]]
    for candidate in candidates:
        try:
            return json.loads(candidate, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError):
            try:
                parsed = ast.literal_eval(candidate)
            except (SyntaxError, ValueError):
                continue
            if isinstance(parsed, (dict, list, tuple, int, float)) and not isinstance(parsed, bool):
                return parsed
    raise ValueError(f"{label} does not contain structured numeric output")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant rejected: {value}")


def _canonical_source(value: Any) -> bytes:
    if isinstance(value, str):
        return value.encode("utf-8")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _render_png(metrics: list[tuple[str, float]]) -> bytes:
    width, height = PLOT_WIDTH, PLOT_HEIGHT
    pixels = bytearray((248, 250, 252) * (width * height))

    def rect(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        x0, x1 = max(0, min(x0, width)), max(0, min(x1, width))
        y0, y1 = max(0, min(y0, height)), max(0, min(y1, height))
        row = bytes(color) * max(0, x1 - x0)
        for y in range(y0, y1):
            start = (y * width + x0) * 3
            pixels[start:start + len(row)] = row

    rect(0, 0, width, 64, (15, 23, 42))
    _draw_text(rect, 30, 21, "VERIFIED METRICS", (241, 245, 249), 3)
    rect(60, 88, 900, 470, (255, 255, 255))
    values = [value for _, value in metrics]
    scale = max(1.0, *(abs(value) for value in values))
    normalized = [value / scale for value in values]
    low, high = min(0.0, min(normalized)), max(0.0, max(normalized))
    if math.isclose(low, high):
        padding = max(1.0, abs(high) * 0.1)
        low -= padding
        high += padding
    top, bottom = 116, 420

    def y_for(value: float) -> int:
        ratio = (value - low) / (high - low)
        return int(round(bottom - ratio * (bottom - top)))

    baseline = y_for(0.0)
    for tick in range(5):
        y = top + tick * (bottom - top) // 4
        rect(80, y, 880, y + 1, (226, 232, 240))
    rect(80, baseline, 880, baseline + 2, (71, 85, 105))
    count = len(metrics)
    cell = 780 / count
    bar_width = max(12, min(54, int(cell * 0.58)))
    palette = ((37, 99, 235), (8, 145, 178), (124, 58, 237), (5, 150, 105))
    for index, ((_, value), normalized_value) in enumerate(zip(metrics, normalized), 1):
        center = int(90 + (index - 0.5) * cell)
        value_y = y_for(normalized_value)
        y0, y1 = sorted((baseline, value_y))
        if y0 == y1:
            y0 = max(top, y0 - 1)
            y1 += 1
        rect(center - bar_width // 2, y0, center + bar_width // 2, y1, palette[(index - 1) % len(palette)])
        _draw_text(rect, center - 7, 438, f"M{index}", (51, 65, 85), 2)
        value_text = f"{value:.4g}".upper()
        text_y = max(94, min(414, value_y - 20 if value >= 0 else value_y + 7))
        _draw_text(rect, center - min(28, len(value_text) * 6), text_y, value_text, (30, 41, 59), 1)

    _draw_text(rect, 80, 492, "METRIC IDS MAP TO THE VERIFIED MANIFEST", (71, 85, 105), 1)
    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3:(y + 1) * width * 3]) for y in range(height))
    png = PNG_SIGNATURE + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _png_chunk(b"IDAT", zlib.compress(raw, 9)) + _png_chunk(b"IEND", b"")
    validate_png(png)
    return png


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return struct.pack(">I", len(data)) + payload + struct.pack(">I", binascii.crc32(payload) & 0xFFFFFFFF)


_FONT = {
    " ": (0, 0, 0, 0, 0, 0, 0), ".": (0, 0, 0, 0, 0, 6, 6), "+": (0, 4, 4, 31, 4, 4, 0), "-": (0, 0, 0, 31, 0, 0, 0),
    "0": (14, 17, 19, 21, 25, 17, 14), "1": (4, 12, 4, 4, 4, 4, 14), "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (30, 1, 1, 14, 1, 1, 30), "4": (2, 6, 10, 18, 31, 2, 2), "5": (31, 16, 16, 30, 1, 1, 30),
    "6": (14, 16, 16, 30, 17, 17, 14), "7": (31, 1, 2, 4, 8, 8, 8), "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 1, 14), "A": (14, 17, 17, 31, 17, 17, 17), "C": (14, 17, 16, 16, 16, 17, 14), "D": (30, 17, 17, 17, 17, 17, 30),
    "E": (31, 16, 16, 30, 16, 16, 31), "F": (31, 16, 16, 30, 16, 16, 16), "H": (17, 17, 17, 31, 17, 17, 17),
    "I": (14, 4, 4, 4, 4, 4, 14), "M": (17, 27, 21, 21, 17, 17, 17), "N": (17, 25, 21, 19, 17, 17, 17), "O": (14, 17, 17, 17, 17, 17, 14),
    "P": (30, 17, 17, 30, 16, 16, 16), "R": (30, 17, 17, 30, 20, 18, 17), "S": (15, 16, 16, 14, 1, 1, 30),
    "T": (31, 4, 4, 4, 4, 4, 4), "V": (17, 17, 17, 17, 17, 10, 4), "Y": (17, 17, 10, 4, 4, 4, 4),
}


def _draw_text(rect, x: int, y: int, text: str, color: tuple[int, int, int], scale: int) -> None:
    cursor = x
    for character in text.upper():
        glyph = _FONT.get(character, _FONT[" "])
        for row, bits in enumerate(glyph):
            for column in range(5):
                if bits & (1 << (4 - column)):
                    rect(cursor + column * scale, y + row * scale, cursor + (column + 1) * scale, y + (row + 1) * scale, color)
        cursor += 6 * scale
