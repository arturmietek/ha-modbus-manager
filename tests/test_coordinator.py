"""Unit tests for coordinator pure logic (_logic.py)."""

import pytest

from custom_components.modbus_manager.coordinator import (
    _WITHHELD as WITHHELD,
    _build_groups as build_groups,
    _device_priority as device_priority,
    _effective_interval as effective_interval,
    ModbusManagerCoordinator,
)
from custom_components.modbus_manager.const import OFFLINE_BACKOFF_CAP_S, CONF_POLL_PRIORITY


def validate_and_track(value, entity, device, last_valid):
    """Call _validate_and_track on a bare coordinator instance."""
    coord = ModbusManagerCoordinator.__new__(ModbusManagerCoordinator)
    coord._last_valid = last_valid
    return coord._validate_and_track(value, entity, device)


# ── helpers ───────────────────────────────────────────────────────────────────

def _e(entity_id: str, address: int, data_type: str = "UINT16") -> dict:
    return {"id": entity_id, "address": address, "data_type": data_type}


def _e32(entity_id: str, address: int) -> dict:
    return {"id": entity_id, "address": address, "data_type": "UINT32"}


def _estr(entity_id: str, address: int, register_count: int = 8) -> dict:
    return {"id": entity_id, "address": address, "data_type": "STRING",
            "register_count": register_count}


def _edef(entity_id: str, validation: dict | None = None) -> dict:
    e: dict = {"id": entity_id}
    if validation:
        e["validation"] = validation
    return e


# ── effective_interval ────────────────────────────────────────────────────────

class TestEffectiveInterval:
    BASE = 30.0
    T = 3  # threshold

    def test_no_failures_returns_base(self):
        assert effective_interval(self.BASE, 0, self.T) == self.BASE

    def test_below_threshold_returns_base(self):
        assert effective_interval(self.BASE, 2, self.T) == self.BASE

    def test_at_threshold_no_backoff(self):
        # fail_count == threshold → steps = 0 → 30 * 2^0 = 30
        assert effective_interval(self.BASE, 3, self.T) == self.BASE

    def test_one_over_threshold_doubles(self):
        assert effective_interval(self.BASE, 4, self.T) == 60.0

    def test_two_over_quadruples(self):
        assert effective_interval(self.BASE, 5, self.T) == 120.0

    def test_three_over_octuples(self):
        assert effective_interval(self.BASE, 6, self.T) == 240.0

    def test_capped_at_offline_backoff_cap(self):
        assert effective_interval(self.BASE, 20, self.T) == OFFLINE_BACKOFF_CAP_S

    def test_cap_is_300_seconds(self):
        assert OFFLINE_BACKOFF_CAP_S == 300

    def test_short_base_also_caps(self):
        assert effective_interval(10.0, 30, self.T) == OFFLINE_BACKOFF_CAP_S


# ── build_groups ──────────────────────────────────────────────────────────────

class TestBuildGroups:
    def test_empty_returns_empty(self):
        assert build_groups([]) == []

    def test_single_uint16(self):
        groups = build_groups([_e("a", 10)])
        assert len(groups) == 1
        start, count, ents = groups[0]
        assert (start, count) == (10, 1)
        assert ents[0]["id"] == "a"

    def test_two_contiguous_merged(self):
        groups = build_groups([_e("a", 0), _e("b", 1)])
        assert len(groups) == 1
        assert groups[0][:2] == (0, 2)

    def test_adjacent_after_uint32_merged(self):
        # uint32 at addr=0 spans regs 0-1; uint16 at addr=2 is adjacent
        groups = build_groups([_e32("a", 0), _e("b", 2)])
        assert len(groups) == 1
        assert groups[0][1] == 3  # count = regs 0,1,2

    def test_gap_creates_two_groups(self):
        groups = build_groups([_e("a", 0), _e("b", 5)])
        assert len(groups) == 2
        assert groups[0][0] == 0
        assert groups[1][0] == 5

    def test_unsorted_input_is_sorted(self):
        groups = build_groups([_e("b", 5), _e("a", 0), _e("c", 1)])
        assert len(groups) == 2
        assert groups[0][0] == 0   # a+c merged
        assert groups[1][0] == 5   # b alone

    def test_string_register_count_respected(self):
        # 7-reg string at addr=0 ends at reg 6; uint16 at addr=7 is adjacent
        groups = build_groups([_estr("sn", 0, 7), _e("x", 7)])
        assert len(groups) == 1
        assert groups[0][1] == 8  # regs 0-7

    def test_string_with_gap(self):
        groups = build_groups([_estr("sn", 0, 7), _e("x", 10)])
        assert len(groups) == 2

    def test_three_groups(self):
        groups = build_groups([
            _e("a", 0), _e("b", 1),    # group 1
            _e("c", 10), _e("d", 11),  # group 2
            _e("e", 20),               # group 3
        ])
        assert len(groups) == 3
        assert [g[0] for g in groups] == [0, 10, 20]
        assert [g[1] for g in groups] == [2, 2, 1]

    def test_overlapping_uint32_extends_group(self):
        # uint32 at addr=5 spans 5-6; uint16 at addr=6 overlaps → one group
        groups = build_groups([_e32("a", 5), _e("b", 6)])
        assert len(groups) == 1
        assert groups[0][:2] == (5, 2)

    def test_span_not_entity_count(self):
        entities = [_e(str(i), i) for i in range(4)]
        groups = build_groups(entities)
        assert len(groups) == 1
        assert groups[0][1] == 4  # span, not entity count


# ── validate_and_track ────────────────────────────────────────────────────────

class TestValidateAndTrack:
    def setup_method(self):
        self.lv: dict = {}  # last_valid cache, shared across calls per test

    def _call(self, value, entity_id="v", validation=None, device="dev"):
        e = _edef(entity_id, validation)
        return validate_and_track(value, e, device, self.lv)

    def test_no_validation_passes_through(self):
        assert self._call(42.0) == 42.0

    def test_no_validation_stores_last_valid(self):
        self._call(99.0)
        assert self.lv["dev"]["v"] == 99.0

    def test_string_value_skips_numeric_validation(self):
        assert self._call("OK", validation={"min": 0, "max": 100}) == "OK"

    def test_none_skips_validation(self):
        assert self._call(None, validation={"min": 0}) is None

    def test_min_pass(self):
        assert self._call(0.0, validation={"min": 0.0}) == 0.0

    def test_min_fail_no_prior_withheld(self):
        assert self._call(5.0, validation={"min": 10.0}) is WITHHELD

    def test_min_fail_returns_last_valid(self):
        self.lv["dev"] = {"v": 50.0}
        assert self._call(5.0, validation={"min": 10.0}) == 50.0

    def test_max_pass(self):
        assert self._call(100.0, validation={"max": 100.0}) == 100.0

    def test_max_fail_no_prior_withheld(self):
        assert self._call(200.0, validation={"max": 100.0}) is WITHHELD

    def test_max_fail_returns_last_valid(self):
        self.lv["dev"] = {"v": 80.0}
        assert self._call(200.0, validation={"max": 100.0}) == 80.0

    def test_max_delta_no_prior_passes(self):
        assert self._call(100.0, validation={"max_delta": 5.0}) == 100.0

    def test_max_delta_within_limit_passes(self):
        self.lv["dev"] = {"v": 100.0}
        assert self._call(104.9, validation={"max_delta": 5.0}) == pytest.approx(104.9)

    def test_max_delta_exceeded_returns_last_valid(self):
        self.lv["dev"] = {"v": 100.0}
        assert self._call(200.0, validation={"max_delta": 5.0}) == 100.0

    def test_max_delta_exact_boundary_passes(self):
        self.lv["dev"] = {"v": 100.0}
        assert self._call(105.0, validation={"max_delta": 5.0}) == pytest.approx(105.0)

    def test_success_updates_last_valid(self):
        self._call(55.0, validation={"min": 0.0, "max": 100.0})
        assert self.lv["dev"]["v"] == pytest.approx(55.0)

    def test_failure_does_not_overwrite_last_valid(self):
        self.lv["dev"] = {"v": 75.0}
        self._call(999.0, validation={"max": 100.0})
        assert self.lv["dev"]["v"] == pytest.approx(75.0)

    def test_separate_devices_isolated(self):
        self.lv["dev1"] = {"v": 50.0}
        # dev2 has no prior
        assert self._call(5.0, validation={"min": 10.0}, device="dev2") is WITHHELD
        # dev1 returns its fallback
        assert self._call(5.0, validation={"min": 10.0}, device="dev1") == 50.0


# ── device_priority ───────────────────────────────────────────────────────────

class TestDevicePriority:
    def test_default_is_zero(self):
        assert device_priority({}) == 0

    def test_yaml_definition_priority(self):
        d = {"definition": {"poll_priority": 10}}
        assert device_priority(d) == 10

    def test_per_device_config_overrides_definition(self):
        d = {CONF_POLL_PRIORITY: 5, "definition": {"poll_priority": 10}}
        assert device_priority(d) == 5

    def test_per_device_config_zero_overrides_definition(self):
        d = {CONF_POLL_PRIORITY: 0, "definition": {"poll_priority": 10}}
        assert device_priority(d) == 0

    def test_sort_order_lower_first(self):
        devices = [
            {"id": "inverter", CONF_POLL_PRIORITY: 10},
            {"id": "meter",    CONF_POLL_PRIORITY: 0},
            {"id": "relay",    CONF_POLL_PRIORITY: 5},
        ]
        ordered = sorted(devices, key=device_priority)
        assert [d["id"] for d in ordered] == ["meter", "relay", "inverter"]

    def test_same_priority_stable(self):
        devices = [
            {"id": "a", CONF_POLL_PRIORITY: 0},
            {"id": "b", CONF_POLL_PRIORITY: 0},
        ]
        ordered = sorted(devices, key=device_priority)
        assert [d["id"] for d in ordered] == ["a", "b"]
