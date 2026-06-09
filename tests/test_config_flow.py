"""Unit tests for config_flow helper functions and voluptuous schema validation."""

import pytest
import voluptuous as vol
import yaml

from custom_components.modbus_manager.config_flow import (
    _slugify,
    _unique_stem,
    _load_builtin_definitions,
    _load_definition,
    _load_user_definitions,
    _load_user_definition,
    _save_user_definition,
)
from custom_components.modbus_manager.const import (
    CONF_DEVICE_NAME,
    CONF_SLAVE_ID,
    CONF_SCAN_INTERVAL,
    CONF_POLL_PRIORITY,
    DEFAULT_SCAN_INTERVAL,
)


# ── _slugify ──────────────────────────────────────────────────────────────────

class TestSlugify:
    def test_simple(self):
        assert _slugify("My Device") == "my_device"

    def test_special_chars(self):
        assert _slugify("SDM-360 / Eastron") == "sdm_360_eastron"

    def test_leading_trailing_stripped(self):
        assert _slugify("---hello---") == "hello"

    def test_empty_falls_back(self):
        assert _slugify("!!!") == "custom_device"

    def test_already_clean(self):
        assert _slugify("sofarsolar_ktl_x") == "sofarsolar_ktl_x"

    def test_numbers_preserved(self):
        assert _slugify("SDM120") == "sdm120"

    def test_mixed_case(self):
        assert _slugify("SofarSolar KTL-X 10kW") == "sofarsolar_ktl_x_10kw"


# ── _unique_stem ──────────────────────────────────────────────────────────────

class TestUniqueStem:
    def test_no_conflict(self, tmp_path):
        assert _unique_stem(str(tmp_path), "my_device") == "my_device"

    def test_conflict_increments(self, tmp_path):
        d = tmp_path / "modbus_manager"
        d.mkdir()
        (d / "my_device.yaml").write_text("x")
        assert _unique_stem(str(tmp_path), "my_device") == "my_device_1"

    def test_two_conflicts(self, tmp_path):
        d = tmp_path / "modbus_manager"
        d.mkdir()
        (d / "my_device.yaml").write_text("x")
        (d / "my_device_1.yaml").write_text("x")
        assert _unique_stem(str(tmp_path), "my_device") == "my_device_2"

    def test_no_modbus_manager_dir(self, tmp_path):
        # Dir doesn't exist yet — no conflict possible
        assert _unique_stem(str(tmp_path), "new_dev") == "new_dev"


# ── _load_builtin_definitions ─────────────────────────────────────────────────

class TestLoadBuiltinDefinitions:
    def test_returns_dict(self):
        result = _load_builtin_definitions()
        assert isinstance(result, dict)

    def test_not_empty(self):
        result = _load_builtin_definitions()
        assert len(result) > 0

    def test_values_are_strings(self):
        for stem, name in _load_builtin_definitions().items():
            assert isinstance(stem, str)
            assert isinstance(name, str)

    def test_known_device_present(self):
        result = _load_builtin_definitions()
        assert "sofarsolar_ktl_x" in result

    def test_names_not_empty(self):
        for name in _load_builtin_definitions().values():
            assert name.strip() != ""

    def test_underscore_prefixed_excluded(self):
        for stem in _load_builtin_definitions():
            assert not stem.startswith("_")


# ── _load_definition ──────────────────────────────────────────────────────────

class TestLoadDefinition:
    def test_known_device_loads(self):
        d = _load_definition("sofarsolar_ktl_x")
        assert isinstance(d, dict)
        assert "entities" in d

    def test_unknown_returns_none(self):
        assert _load_definition("nonexistent_device_xyz") is None

    def test_has_name_field(self):
        d = _load_definition("sofarsolar_ktl_x")
        assert "name" in d

    def test_entities_is_list(self):
        d = _load_definition("sofarsolar_ktl_x")
        assert isinstance(d["entities"], list)
        assert len(d["entities"]) > 0


# ── user definition filesystem helpers ───────────────────────────────────────

class TestUserDefinitions:
    def test_load_user_definitions_empty_dir(self, tmp_path):
        d = tmp_path / "modbus_manager"
        d.mkdir()
        assert _load_user_definitions(str(tmp_path)) == {}

    def test_load_user_definitions_no_dir(self, tmp_path):
        assert _load_user_definitions(str(tmp_path)) == {}

    def test_save_and_load(self, tmp_path):
        content = "name: Test\nentities: []\n"
        _save_user_definition(str(tmp_path), "my_dev", content)
        result = _load_user_definitions(str(tmp_path))
        assert "my_dev" in result
        assert result["my_dev"] == "Test"

    def test_load_user_definition_returns_dict(self, tmp_path):
        content = "name: Test\nentities: []\n"
        _save_user_definition(str(tmp_path), "my_dev", content)
        d = _load_user_definition(str(tmp_path), "my_dev")
        assert isinstance(d, dict)
        assert d["name"] == "Test"

    def test_load_user_definition_missing_returns_none(self, tmp_path):
        assert _load_user_definition(str(tmp_path), "ghost") is None

    def test_save_creates_subdirectory(self, tmp_path):
        _save_user_definition(str(tmp_path), "dev", "name: X\n")
        assert (tmp_path / "modbus_manager" / "dev.yaml").exists()


# ── add_device schema validation ──────────────────────────────────────────────

ADD_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_NAME): str,
        vol.Required(CONF_SLAVE_ID, default=1): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=247)
        ),
        vol.Required(CONF_SCAN_INTERVAL, default=float(DEFAULT_SCAN_INTERVAL)): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=3600)
        ),
        vol.Required(CONF_POLL_PRIORITY, default=0): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
    }
)


class TestAddDeviceSchema:
    def _valid(self):
        return {
            CONF_DEVICE_NAME: "My Meter",
            CONF_SLAVE_ID: 1,
            CONF_SCAN_INTERVAL: 10.0,
            CONF_POLL_PRIORITY: 0,
        }

    def test_valid_input_passes(self):
        result = ADD_DEVICE_SCHEMA(self._valid())
        assert result[CONF_DEVICE_NAME] == "My Meter"

    def test_slave_id_min(self):
        data = {**self._valid(), CONF_SLAVE_ID: 1}
        assert ADD_DEVICE_SCHEMA(data)[CONF_SLAVE_ID] == 1

    def test_slave_id_max(self):
        data = {**self._valid(), CONF_SLAVE_ID: 247}
        assert ADD_DEVICE_SCHEMA(data)[CONF_SLAVE_ID] == 247

    def test_slave_id_zero_rejected(self):
        with pytest.raises(vol.Invalid):
            ADD_DEVICE_SCHEMA({**self._valid(), CONF_SLAVE_ID: 0})

    def test_slave_id_248_rejected(self):
        with pytest.raises(vol.Invalid):
            ADD_DEVICE_SCHEMA({**self._valid(), CONF_SLAVE_ID: 248})

    def test_scan_interval_min(self):
        data = {**self._valid(), CONF_SCAN_INTERVAL: 0.5}
        assert ADD_DEVICE_SCHEMA(data)[CONF_SCAN_INTERVAL] == pytest.approx(0.5)

    def test_scan_interval_too_low_rejected(self):
        with pytest.raises(vol.Invalid):
            ADD_DEVICE_SCHEMA({**self._valid(), CONF_SCAN_INTERVAL: 0.4})

    def test_scan_interval_max(self):
        data = {**self._valid(), CONF_SCAN_INTERVAL: 3600.0}
        assert ADD_DEVICE_SCHEMA(data)[CONF_SCAN_INTERVAL] == pytest.approx(3600.0)

    def test_scan_interval_too_high_rejected(self):
        with pytest.raises(vol.Invalid):
            ADD_DEVICE_SCHEMA({**self._valid(), CONF_SCAN_INTERVAL: 3601.0})

    def test_poll_priority_zero(self):
        data = {**self._valid(), CONF_POLL_PRIORITY: 0}
        assert ADD_DEVICE_SCHEMA(data)[CONF_POLL_PRIORITY] == 0

    def test_poll_priority_max(self):
        data = {**self._valid(), CONF_POLL_PRIORITY: 100}
        assert ADD_DEVICE_SCHEMA(data)[CONF_POLL_PRIORITY] == 100

    def test_poll_priority_negative_rejected(self):
        with pytest.raises(vol.Invalid):
            ADD_DEVICE_SCHEMA({**self._valid(), CONF_POLL_PRIORITY: -1})

    def test_poll_priority_over_max_rejected(self):
        with pytest.raises(vol.Invalid):
            ADD_DEVICE_SCHEMA({**self._valid(), CONF_POLL_PRIORITY: 101})

    def test_poll_priority_coerced_from_string(self):
        data = {**self._valid(), CONF_POLL_PRIORITY: "5"}
        assert ADD_DEVICE_SCHEMA(data)[CONF_POLL_PRIORITY] == 5

    def test_missing_device_name_rejected(self):
        data = self._valid()
        del data[CONF_DEVICE_NAME]
        with pytest.raises(vol.Invalid):
            ADD_DEVICE_SCHEMA(data)


# ── upload_custom YAML validation ─────────────────────────────────────────────

class TestUploadCustomYaml:
    """Test the YAML parsing logic used in async_step_upload_custom."""

    def _parse(self, text: str):
        try:
            definition = yaml.safe_load(text)
        except yaml.YAMLError:
            return "invalid_yaml", None
        if not isinstance(definition, dict) or "entities" not in definition:
            return "invalid_definition", None
        return None, definition

    def test_valid_yaml_passes(self):
        text = "name: My Dev\nentities:\n  - id: sensor_a\n"
        error, d = self._parse(text)
        assert error is None
        assert d["name"] == "My Dev"

    def test_bad_yaml_returns_invalid_yaml(self):
        error, _ = self._parse("key: [unclosed")
        assert error == "invalid_yaml"

    def test_valid_yaml_without_entities_key(self):
        error, _ = self._parse("name: X\n")
        assert error == "invalid_definition"

    def test_entities_is_list_not_dict(self):
        # entities present but as a non-dict top-level is still valid (list is fine)
        error, d = self._parse("entities:\n  - id: x\n")
        assert error is None

    def test_empty_entities_list_accepted(self):
        error, d = self._parse("name: X\nentities: []\n")
        assert error is None
        assert d["entities"] == []

    def test_non_dict_top_level(self):
        error, _ = self._parse("- item1\n- item2\n")
        assert error == "invalid_definition"

    def test_null_document(self):
        error, _ = self._parse("")
        assert error == "invalid_definition"
