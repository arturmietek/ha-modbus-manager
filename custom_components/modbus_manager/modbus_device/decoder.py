"""Decode raw Modbus register words to Python values."""
from __future__ import annotations
import struct

from .model import REGISTER_COUNT


def decode_value(
    raw: list[int],
    data_type: str = "UINT16",
    byte_order: str = "BIG",
    scale: float = 1.0,
    offset: float = 0.0,
) -> int | float:
    """Convert raw register word(s) to a scaled Python number."""
    if data_type == "UINT16":
        return raw[0] * scale + offset

    if data_type == "INT16":
        v = raw[0]
        if v >= 0x8000:
            v -= 0x10000
        return v * scale + offset

    if data_type in ("UINT32", "INT32", "FLOAT32"):
        r0, r1 = raw[0], raw[1]
        if byte_order == "BIG":
            packed = struct.pack(">HH", r0, r1)
        elif byte_order == "LITTLE":
            packed = struct.pack(">HH", r1, r0)
        elif byte_order == "BIG_SWAP":
            packed = struct.pack(">HH", _swap(r0), _swap(r1))
        else:  # LITTLE_SWAP
            packed = struct.pack(">HH", _swap(r1), _swap(r0))
        if data_type == "FLOAT32":
            return struct.unpack(">f", packed)[0] * scale + offset
        if data_type == "UINT32":
            return struct.unpack(">I", packed)[0] * scale + offset
        return struct.unpack(">i", packed)[0] * scale + offset

    if data_type == "INT64":
        if byte_order in ("BIG", "BIG_SWAP"):
            packed = struct.pack(">HHHH", *raw[:4])
        else:
            packed = struct.pack(">HHHH", *reversed(raw[:4]))
        return struct.unpack(">q", packed)[0] * scale + offset

    return raw[0] * scale + offset  # unknown → UINT16 fallback


def _swap(v: int) -> int:
    return ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)


def apply_value_map(value, value_map: dict):
    """Apply a value_map dict to a decoded value. Returns mapped result or original."""
    if not value_map:
        return value
    if value in value_map:
        return value_map[value]
    # Numeric coercion: 2.0 → 2
    if isinstance(value, float) and value.is_integer():
        int_val = int(value)
        if int_val in value_map:
            return value_map[int_val]
    str_val = str(value)
    if str_val in value_map:
        return value_map[str_val]
    return value


def format_value(value, precision: int | None, unit: str) -> str:
    """Format a decoded value for display, appending unit if present."""
    if value is None:
        return "—"
    if value == "ERR":
        return "ERR"
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        s = str(value)
    elif isinstance(value, float):
        if precision is not None:
            s = f"{value:.{precision}f}"
        elif value == int(value) and abs(value) < 1e9:
            s = str(int(value))
        else:
            s = f"{value:.4g}"
    else:
        s = str(value)
    return f"{s} {unit}" if unit else s
