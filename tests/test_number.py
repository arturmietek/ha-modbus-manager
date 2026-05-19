"""Unit tests for number._to_raw."""

import pytest

from custom_components.modbus_manager.number import _to_raw
from custom_components.modbus_manager.const import DATA_TYPE_UINT16, DATA_TYPE_INT16


# ── UINT16 ────────────────────────────────────────────────────────────────────

class TestToRawUINT16:
    def _raw(self, display, scale=1.0, offset=0.0):
        return _to_raw(display, scale, offset, DATA_TYPE_UINT16)

    def test_zero(self):
        assert self._raw(0.0) == 0

    def test_max(self):
        assert self._raw(65535.0) == 65535

    def test_negative_returns_none(self):
        assert self._raw(-1.0) is None

    def test_above_max_returns_none(self):
        assert self._raw(65536.0) is None

    def test_scale_divide(self):
        # display=10.0, scale=0.1 → raw = 10/0.1 = 100
        assert self._raw(10.0, scale=0.1) == 100

    def test_scale_multiply(self):
        # display=5, scale=10 → raw = 5/10 = 0.5 → banker's rounding → 0
        assert self._raw(5.0, scale=10.0) == 0

    def test_offset_subtracted(self):
        # display=15, offset=5, scale=1 → raw = (15-5)/1 = 10
        assert self._raw(15.0, scale=1.0, offset=5.0) == 10

    def test_scale_and_offset(self):
        # display=20, offset=10, scale=0.1 → raw = (20-10)/0.1 = 100
        assert self._raw(20.0, scale=0.1, offset=10.0) == 100

    def test_rounding_up(self):
        # (0.55 - 0) / 0.1 = 5.5 → rounds to 6
        assert self._raw(0.55, scale=0.1) == 6

    def test_rounding_down(self):
        # (0.54 - 0) / 0.1 = 5.4 → rounds to 5
        assert self._raw(0.54, scale=0.1) == 5

    def test_typical_power_register(self):
        # Power in 0.1 W resolution: display=23.4 kW → raw=234
        assert self._raw(23.4, scale=0.1) == 234

    def test_boundary_zero_exact(self):
        assert self._raw(0.0) == 0

    def test_boundary_max_exact(self):
        assert self._raw(65535.0) == 65535

    def test_just_below_zero_rejected(self):
        # -0.6 rounds to -1, which is below UINT16 minimum
        assert self._raw(-0.6, scale=1.0) is None


# ── INT16 ─────────────────────────────────────────────────────────────────────

class TestToRawINT16:
    def _raw(self, display, scale=1.0, offset=0.0):
        return _to_raw(display, scale, offset, DATA_TYPE_INT16)

    def test_zero(self):
        assert self._raw(0.0) == 0

    def test_positive(self):
        assert self._raw(100.0) == 100

    def test_max_positive(self):
        assert self._raw(32767.0) == 32767

    def test_above_max_returns_none(self):
        assert self._raw(32768.0) is None

    def test_negative_one_twos_complement(self):
        # -1 → 0xFFFF = 65535
        assert self._raw(-1.0) == 65535

    def test_min_negative(self):
        # -32768 → 0x8000 = 32768
        assert self._raw(-32768.0) == 32768

    def test_below_min_returns_none(self):
        assert self._raw(-32769.0) is None

    def test_negative_with_scale(self):
        # display=-10.0, scale=0.1 → raw=-100 → two's complement: 65436
        assert self._raw(-10.0, scale=0.1) == 65436

    def test_positive_with_scale(self):
        # display=5.0, scale=0.1 → raw=50
        assert self._raw(5.0, scale=0.1) == 50

    def test_temperature_typical(self):
        # Temperature offset=-40: display=25°C, offset=-40, scale=1 → raw=65
        assert self._raw(25.0, scale=1.0, offset=-40.0) == 65

    def test_negative_temperature(self):
        # display=-10°C, offset=-40, scale=1 → raw=30
        assert self._raw(-10.0, scale=1.0, offset=-40.0) == 30


# ── Unknown / fallback type ───────────────────────────────────────────────────

class TestToRawFallback:
    def test_unknown_type_behaves_like_uint16(self):
        assert _to_raw(100.0, 1.0, 0.0, "UNKNOWN") == 100

    def test_unknown_type_rejects_negative(self):
        assert _to_raw(-1.0, 1.0, 0.0, "UNKNOWN") is None

    def test_unknown_type_rejects_above_uint16_max(self):
        assert _to_raw(65536.0, 1.0, 0.0, "UNKNOWN") is None
