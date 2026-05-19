"""Unit tests for sensor._resolve_state_class."""

import pytest

from custom_components.modbus_manager.sensor import _resolve_state_class
from custom_components.modbus_manager.const import ENTITY_TYPE_TEXT


# The stub SensorStateClass is a str-enum so we compare by value string.
MEASUREMENT = "measurement"
TOTAL = "total"
TOTAL_INCREASING = "total_increasing"


class TestResolveStateClass:
    # ── text / STRING entities ─────────────────────────────────────────────

    def test_string_data_type_returns_none(self):
        assert _resolve_state_class({"data_type": "STRING"}) is None

    def test_text_entity_type_returns_none(self):
        assert _resolve_state_class({"entity_type": ENTITY_TYPE_TEXT}) is None

    def test_text_entity_with_explicit_state_class_still_none(self):
        # entity_type=text overrides any explicit state_class
        e = {"entity_type": ENTITY_TYPE_TEXT, "state_class": "measurement"}
        assert _resolve_state_class(e) is None

    def test_string_data_type_with_explicit_state_class_still_none(self):
        e = {"data_type": "STRING", "state_class": "total"}
        assert _resolve_state_class(e) is None

    # ── default → MEASUREMENT ─────────────────────────────────────────────

    def test_empty_entity_def_defaults_to_measurement(self):
        result = _resolve_state_class({})
        assert result == MEASUREMENT

    def test_numeric_entity_without_state_class_defaults_to_measurement(self):
        result = _resolve_state_class({"data_type": "UINT16", "unit": "W"})
        assert result == MEASUREMENT

    def test_uint32_defaults_to_measurement(self):
        result = _resolve_state_class({"data_type": "UINT32"})
        assert result == MEASUREMENT

    def test_float32_defaults_to_measurement(self):
        result = _resolve_state_class({"data_type": "FLOAT32"})
        assert result == MEASUREMENT

    # ── explicit state_class from YAML ────────────────────────────────────

    def test_explicit_measurement(self):
        result = _resolve_state_class({"state_class": "measurement"})
        assert result == MEASUREMENT

    def test_explicit_total(self):
        result = _resolve_state_class({"state_class": "total"})
        assert result == TOTAL

    def test_explicit_total_increasing(self):
        result = _resolve_state_class({"state_class": "total_increasing"})
        assert result == TOTAL_INCREASING

    def test_invalid_state_class_returns_none(self):
        result = _resolve_state_class({"state_class": "bogus_value"})
        assert result is None

    def test_kwh_energy_counter_total_increasing(self):
        # Realistic: energy meter entity with explicit counter state_class
        e = {"data_type": "UINT32", "unit": "kWh", "state_class": "total_increasing"}
        assert _resolve_state_class(e) == TOTAL_INCREASING

    # ── value_map / bitmask override (applied by caller) ─────────────────
    # _resolve_state_class itself does NOT apply value_map override —
    # that's the caller's responsibility. Verify this function does not touch it.

    def test_value_map_not_overridden_by_resolve(self):
        # value_map present — resolve returns MEASUREMENT (override is caller's job)
        e = {"value_map": {0: "OFF", 1: "ON"}}
        assert _resolve_state_class(e) == MEASUREMENT

    def test_bitmask_not_overridden_by_resolve(self):
        e = {"bitmask": {0: "Fault A"}}
        assert _resolve_state_class(e) == MEASUREMENT
