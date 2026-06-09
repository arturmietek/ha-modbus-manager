"""Decode raw Modbus register words to Python values."""
from __future__ import annotations
import struct



def decode_value(
    raw: list[int],
    data_type: str = "UINT16",
    byte_order: str = "BIG",
    scale: float = 1.0,
    offset: float = 0.0,
) -> int | float | str:
    """Convert raw register word(s) to a Python value."""
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

    if data_type == "STRING":
        chars = []
        for reg in raw:
            high = (reg >> 8) & 0xFF
            low = reg & 0xFF
            if high:
                chars.append(chr(high))
            if low:
                chars.append(chr(low))
        return "".join(chars).strip("\x00")

    return raw[0] * scale + offset  # unknown → UINT16 fallback


def _swap(v: int) -> int:
    return ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)


def apply_bitmask(raw: int, bitmask: dict) -> str:
    """Decode active bit flags from a raw integer using a bit-index → label mapping.

    Returns a comma-separated string of active flag labels, or "OK" when all bits are clear.
    Keys may be ints or strings; values are the human-readable label for that bit.
    """
    active = [
        str(label)
        for bit, label in sorted(bitmask.items(), key=lambda x: int(x[0]))
        if int(raw) & (1 << int(bit))
    ]
    return ", ".join(active) if active else "OK"


def apply_value_map(value, value_map: dict):
    """Apply a value_map dict to a decoded value. Returns mapped result or original.

    Lookup order: exact match → int coercion → str(int) coercion.
    Handles bool bits from coil reads (True/False) and numeric float→int coercion.
    """
    if not value_map:
        return value
    # Exact match — handles bool True/False correctly via Python's == and hash
    if value in value_map:
        return value_map[value]
    # Numeric coercion: int(2.0) → 2, int(True) → 1, int(False) → 0
    try:
        as_int = int(value)
        if as_int in value_map:
            return value_map[as_int]
        as_str = str(as_int)
        if as_str in value_map:
            return value_map[as_str]
    except (ValueError, TypeError):
        pass
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
