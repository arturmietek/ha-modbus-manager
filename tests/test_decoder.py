"""Unit tests for modbus_device.decoder."""
import math
import struct

import pytest

from modbus_device.decoder import apply_bitmask, apply_value_map, decode_value, format_value


# ── decode_value ──────────────────────────────────────────────────────────────

class TestDecodeUINT16:
    def test_basic(self):
        assert decode_value([100], "UINT16") == 100

    def test_scale(self):
        assert decode_value([1234], "UINT16", scale=0.1) == pytest.approx(123.4)

    def test_offset(self):
        assert decode_value([10], "UINT16", offset=5.0) == pytest.approx(15.0)

    def test_scale_and_offset(self):
        assert decode_value([100], "UINT16", scale=0.1, offset=-5.0) == pytest.approx(5.0)

    def test_zero(self):
        assert decode_value([0], "UINT16") == 0

    def test_max(self):
        assert decode_value([0xFFFF], "UINT16") == 65535


class TestDecodeINT16:
    def test_positive(self):
        assert decode_value([100], "INT16") == 100

    def test_negative(self):
        # 0xFFF6 = 65526 unsigned = -10 signed
        assert decode_value([0xFFF6], "INT16") == -10

    def test_minus_one(self):
        assert decode_value([0xFFFF], "INT16") == -1

    def test_scale_negative(self):
        assert decode_value([0xFFF6], "INT16", scale=10) == pytest.approx(-100)


class TestDecodeUINT32:
    def test_big_endian(self):
        # 0x00010000 = 65536
        assert decode_value([0x0001, 0x0000], "UINT32", "BIG") == 65536

    def test_little_endian(self):
        # little: low word first → [0x0000, 0x0001] = 0x00010000 = 65536
        assert decode_value([0x0000, 0x0001], "UINT32", "LITTLE") == 65536

    def test_scale(self):
        assert decode_value([0x0000, 0x000A], "UINT32", "BIG", scale=0.1) == pytest.approx(1.0)

    def test_large_value(self):
        assert decode_value([0xFFFF, 0xFFFF], "UINT32", "BIG") == 4294967295


class TestDecodeINT32:
    def test_positive(self):
        assert decode_value([0x0000, 0x0064], "INT32", "BIG") == 100

    def test_negative(self):
        # -1 = 0xFFFFFFFF
        assert decode_value([0xFFFF, 0xFFFF], "INT32", "BIG") == -1

    def test_negative_large(self):
        # -65536 = 0xFFFF0000
        assert decode_value([0xFFFF, 0x0000], "INT32", "BIG") == -65536


class TestDecodeFLOAT32:
    def test_known_value(self):
        # Pack 1.0 as big-endian float32 → two registers
        packed = struct.pack(">f", 1.0)
        r0 = struct.unpack(">H", packed[0:2])[0]
        r1 = struct.unpack(">H", packed[2:4])[0]
        assert decode_value([r0, r1], "FLOAT32", "BIG") == pytest.approx(1.0)

    def test_negative(self):
        packed = struct.pack(">f", -3.14)
        r0 = struct.unpack(">H", packed[0:2])[0]
        r1 = struct.unpack(">H", packed[2:4])[0]
        assert decode_value([r0, r1], "FLOAT32", "BIG") == pytest.approx(-3.14, rel=1e-5)

    def test_nan_passthrough(self):
        packed = struct.pack(">f", float("nan"))
        r0 = struct.unpack(">H", packed[0:2])[0]
        r1 = struct.unpack(">H", packed[2:4])[0]
        result = decode_value([r0, r1], "FLOAT32", "BIG")
        assert math.isnan(result)


class TestDecodeSTRING:
    def test_ascii(self):
        # "AB" = 0x4142
        assert decode_value([0x4142], "STRING") == "AB"

    def test_multi_register(self):
        # "SF" = 0x5346, "4E" = 0x3445
        assert decode_value([0x5346, 0x3445], "STRING") == "SF4E"

    def test_null_termination(self):
        # "A\x00" — null byte should be stripped
        assert decode_value([0x4100], "STRING") == "A"

    def test_serial_number(self):
        # SF4ES005 (first 4 registers of KTL-X serial)
        regs = [0x5346, 0x3445, 0x5330, 0x3035]
        assert decode_value(regs, "STRING") == "SF4ES005"


class TestDecodeINT64:
    def _regs(self, value: int) -> list[int]:
        packed = struct.pack(">q", value)
        return [struct.unpack(">H", packed[i:i+2])[0] for i in range(0, 8, 2)]

    def test_zero(self):
        assert decode_value([0, 0, 0, 0], "INT64") == 0.0

    def test_one(self):
        assert decode_value(self._regs(1), "INT64") == pytest.approx(1.0)

    def test_large_positive(self):
        v = 1_000_000_000_000
        assert decode_value(self._regs(v), "INT64") == pytest.approx(float(v))

    def test_negative_one(self):
        assert decode_value(self._regs(-1), "INT64") == pytest.approx(-1.0)

    def test_negative_large(self):
        v = -1_000_000_000_000
        assert decode_value(self._regs(v), "INT64") == pytest.approx(float(v))

    def test_little_endian(self):
        regs_big = self._regs(9876543210)
        regs_little = list(reversed(regs_big))
        assert decode_value(regs_little, "INT64", "LITTLE") == pytest.approx(9876543210.0)

    def test_scale(self):
        regs = self._regs(10000)
        assert decode_value(regs, "INT64", scale=0.01) == pytest.approx(100.0)


class TestByteOrderSwap:
    @staticmethod
    def _swap(v: int) -> int:
        return ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)

    def _pack32_big(self, value: int) -> list[int]:
        packed = struct.pack(">I", value & 0xFFFFFFFF)
        return [struct.unpack(">H", packed[i:i+2])[0] for i in (0, 2)]

    def test_big_swap_uint32(self):
        big_regs = self._pack32_big(0x12345678)
        swapped = [self._swap(big_regs[0]), self._swap(big_regs[1])]
        assert decode_value(swapped, "UINT32", "BIG_SWAP") == pytest.approx(0x12345678)

    def test_little_swap_uint32(self):
        big_regs = self._pack32_big(0x12345678)
        swapped = [self._swap(big_regs[1]), self._swap(big_regs[0])]
        assert decode_value(swapped, "UINT32", "LITTLE_SWAP") == pytest.approx(0x12345678)

    def test_big_swap_float32(self):
        packed = struct.pack(">f", 2.5)
        r0 = struct.unpack(">H", packed[0:2])[0]
        r1 = struct.unpack(">H", packed[2:4])[0]
        swapped = [self._swap(r0), self._swap(r1)]
        assert decode_value(swapped, "FLOAT32", "BIG_SWAP") == pytest.approx(2.5)

    def test_big_and_big_swap_differ(self):
        # Verify that BIG and BIG_SWAP actually decode differently when bytes are swapped
        regs = [0x3F80, 0x0000]  # big-endian 1.0f
        big_result = decode_value(regs, "FLOAT32", "BIG")
        big_swap_result = decode_value(regs, "FLOAT32", "BIG_SWAP")
        assert big_result != big_swap_result


class TestDecodeUnknownType:
    def test_falls_back_to_uint16(self):
        assert decode_value([42], "NONEXISTENT") == 42


# ── apply_value_map ───────────────────────────────────────────────────────────

class TestApplyValueMap:
    def test_empty_map(self):
        assert apply_value_map(5, {}) == 5

    def test_exact_int_match(self):
        assert apply_value_map(2, {2: "Normal"}) == "Normal"

    def test_float_coercion(self):
        # decode_value returns float; map has int keys
        assert apply_value_map(2.0, {2: "Normal"}) == "Normal"

    def test_string_key_match(self):
        assert apply_value_map(3, {"3": "Fault"}) == "Fault"

    def test_no_match_returns_original(self):
        assert apply_value_map(99, {0: "Wait", 1: "Check"}) == 99

    def test_bool_true(self):
        assert apply_value_map(True, {1: "ON", 0: "OFF"}) == "ON"

    def test_bool_false(self):
        assert apply_value_map(False, {1: "ON", 0: "OFF"}) == "OFF"

    def test_none_value_in_map(self):
        assert apply_value_map(0, {0: None}) is None


# ── apply_bitmask ─────────────────────────────────────────────────────────────

class TestApplyBitmask:
    def test_all_clear_returns_ok(self):
        assert apply_bitmask(0, {0: "Fault A", 1: "Fault B"}) == "OK"

    def test_single_bit(self):
        assert apply_bitmask(1, {0: "Fault A", 1: "Fault B"}) == "Fault A"

    def test_multiple_bits(self):
        result = apply_bitmask(0b0101, {0: "A", 1: "B", 2: "C", 3: "D"})
        assert result == "A, C"

    def test_sorted_by_bit_index(self):
        # Bits 3 and 0 set — result must be in bit-index order
        result = apply_bitmask(0b1001, {0: "Low", 3: "High"})
        assert result == "Low, High"

    def test_string_keys(self):
        # YAML may load bitmask keys as strings
        assert apply_bitmask(5, {"0": "X", "1": "Y", "2": "Z"}) == "X, Z"

    def test_high_bit(self):
        assert apply_bitmask(1 << 9, {9: "Grid Impedance High"}) == "Grid Impedance High"

    def test_all_bits_set(self):
        bitmask = {0: "A", 1: "B", 2: "C"}
        result = apply_bitmask(0b111, bitmask)
        assert result == "A, B, C"

    def test_undefined_bits_ignored(self):
        # Bit 5 is set but not in bitmask — should be silently ignored
        assert apply_bitmask(0b100001, {0: "A"}) == "A"


# ── format_value ──────────────────────────────────────────────────────────────

class TestFormatValue:
    def test_none_returns_dash(self):
        assert format_value(None, None, "") == "—"

    def test_err_passthrough(self):
        assert format_value("ERR", None, "") == "ERR"

    def test_arbitrary_string_passthrough(self):
        assert format_value("SN1234AB", None, "") == "SN1234AB"

    def test_integer_float_no_decimals(self):
        # 42.0 should render as "42", not "42.0"
        assert format_value(42.0, None, "") == "42"

    def test_integer_float_with_unit(self):
        assert format_value(100.0, None, "W") == "100 W"

    def test_precision_zero(self):
        assert format_value(3.7, 0, "") == "4"

    def test_precision_two(self):
        assert format_value(3.14159, 2, "") == "3.14"

    def test_precision_with_unit(self):
        assert format_value(1.5, 1, "kW") == "1.5 kW"

    def test_no_unit_no_trailing_space(self):
        result = format_value(10.0, None, "")
        assert not result.endswith(" ")

    def test_bool_true(self):
        assert format_value(True, None, "") == "True"

    def test_bool_false(self):
        assert format_value(False, None, "") == "False"

    def test_large_float_uses_scientific(self):
        # Values ≥ 1e9 exceed the int-coercion guard and use 4g format
        result = format_value(1.5e10, None, "")
        assert "e" in result.lower()

    def test_small_nonzero_decimal(self):
        assert format_value(0.001, 3, "") == "0.001"
