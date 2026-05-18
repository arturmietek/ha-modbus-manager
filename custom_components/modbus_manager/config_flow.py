"""Config flow and Options flow for Modbus Manager."""
from __future__ import annotations

import re
import uuid
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol
import yaml

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_BUS_TYPE,
    CONF_BUS_TYPE_RTU,
    CONF_BUS_TYPE_TCP,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONF_HOST,
    CONF_TCP_PORT,
    CONF_TIMEOUT,
    CONF_DEVICES,
    CONF_DEVICE_ID,
    CONF_DEVICE_NAME,
    CONF_SLAVE_ID,
    CONF_SCAN_INTERVAL,
    CONF_DEFINITION,
    CONF_DEFINITION_SOURCE,
    CONF_DEFINITION_BUILTIN,
    CONF_DEFINITION_CUSTOM,
    CONF_DEFINITION_USER,
    CONF_DEFINITION_FILE,
    CONF_DEFINITION_USER_FILE,
    CONF_DEFINITION_YAML,
    CONF_DEVICE_PARAMS,
    CONF_DEVICE_ENABLED,
    DEFAULT_BAUDRATE,
    DEFAULT_PARITY,
    DEFAULT_STOPBITS,
    DEFAULT_BYTESIZE,
    DEFAULT_TCP_PORT,
    DEFAULT_TIMEOUT,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

DEFINITIONS_DIR = Path(__file__).parent / "device_definitions"
USER_DEFINITIONS_SUBDIR = "modbus_manager"


def _user_definitions_dir(config_dir: str) -> Path:
    return Path(config_dir) / USER_DEFINITIONS_SUBDIR


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "custom_device"


def _unique_stem(config_dir: str, base: str) -> str:
    d = _user_definitions_dir(config_dir)
    stem = base
    counter = 1
    while (d / f"{stem}.yaml").exists():
        stem = f"{base}_{counter}"
        counter += 1
    return stem


def _load_user_definitions(config_dir: str) -> dict[str, str]:
    """Return {stem: display_name} for user YAML files in config dir."""
    result = {}
    d = _user_definitions_dir(config_dir)
    if d.is_dir():
        for path in sorted(d.glob("*.yaml")):
            try:
                with path.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                result[path.stem] = data.get("name", path.stem)
            except Exception:  # noqa: BLE001
                result[path.stem] = path.stem
    return result


def _load_user_definition(config_dir: str, stem: str) -> dict | None:
    path = _user_definitions_dir(config_dir) / f"{stem}.yaml"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _save_user_definition(config_dir: str, stem: str, content: str) -> None:
    d = _user_definitions_dir(config_dir)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stem}.yaml").write_text(content, encoding="utf-8")


def _load_builtin_definitions() -> dict[str, str]:
    """Return {stem: display_name} for all built-in device definitions."""
    result = {}
    if DEFINITIONS_DIR.is_dir():
        for path in sorted(DEFINITIONS_DIR.glob("*.yaml")):
            if path.stem.startswith("_"):
                continue
            try:
                with path.open(encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                result[path.stem] = data.get("name", path.stem)
            except Exception:  # noqa: BLE001
                result[path.stem] = path.stem
    return result


def _load_definition(stem: str) -> dict | None:
    path = DEFINITIONS_DIR / f"{stem}.yaml"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class ModbusManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of a Modbus bus."""

    VERSION = 1

    def __init__(self) -> None:
        self._bus_data: dict = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Step 1 — choose bus type."""
        if user_input is not None:
            self._bus_data[CONF_BUS_TYPE] = user_input[CONF_BUS_TYPE]
            if user_input[CONF_BUS_TYPE] == CONF_BUS_TYPE_RTU:
                return await self.async_step_rtu()
            return await self.async_step_tcp()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BUS_TYPE, default=CONF_BUS_TYPE_RTU): vol.In(
                        {CONF_BUS_TYPE_RTU: "RTU (USB/Serial)", CONF_BUS_TYPE_TCP: "TCP (Ethernet/WiFi)"}
                    )
                }
            ),
        )

    async def async_step_rtu(self, user_input: dict | None = None) -> FlowResult:
        """Step 2a — RTU parameters."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._bus_data.update(user_input)
            title = f"Modbus RTU — {user_input[CONF_PORT]}"
            await self.async_set_unique_id(f"modbus_manager_{user_input[CONF_PORT]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=title,
                data=self._bus_data,
                options={CONF_DEVICES: []},
            )

        return self.async_show_form(
            step_id="rtu",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PORT, default="/dev/ttyUSB0"): str,
                    vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): vol.In(
                        [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]
                    ),
                    vol.Required(CONF_PARITY, default=DEFAULT_PARITY): vol.In(
                        {"N": "None", "E": "Even", "O": "Odd"}
                    ),
                    vol.Required(CONF_STOPBITS, default=DEFAULT_STOPBITS): vol.In([1, 2]),
                    vol.Required(CONF_BYTESIZE, default=DEFAULT_BYTESIZE): vol.In([7, 8]),
                    vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=30)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_tcp(self, user_input: dict | None = None) -> FlowResult:
        """Step 2b — TCP parameters."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._bus_data.update(user_input)
            title = f"Modbus TCP — {user_input[CONF_HOST]}:{user_input[CONF_TCP_PORT]}"
            await self.async_set_unique_id(
                f"modbus_manager_{user_input[CONF_HOST]}_{user_input[CONF_TCP_PORT]}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=title,
                data=self._bus_data,
                options={CONF_DEVICES: []},
            )

        return self.async_show_form(
            step_id="tcp",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_TCP_PORT, default=DEFAULT_TCP_PORT): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=65535)
                    ),
                    vol.Required(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=30)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> ModbusManagerOptionsFlow:
        return ModbusManagerOptionsFlow(config_entry)


class ModbusManagerOptionsFlow(config_entries.OptionsFlow):
    """Manage devices attached to this bus."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry
        self._devices: list[dict] = list(config_entry.options.get(CONF_DEVICES, []))
        self._new_device: dict = {}
        self._editing_device_id: str = ""

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Main options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_device", "edit_device", "remove_device", "finish"],
        )

    async def async_step_finish(self, user_input: dict | None = None) -> FlowResult:
        return self.async_create_entry(data={CONF_DEVICES: self._devices})

    # ── Add device flow ───────────────────────────────────────────────────────

    async def async_step_add_device(self, user_input: dict | None = None) -> FlowResult:
        """Step: basic device info (name, slave ID, poll interval)."""
        errors: dict[str, str] = {}
        bus_default = float(self._config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL))

        if user_input is not None:
            slave_id = user_input[CONF_SLAVE_ID]
            existing_slave_ids = {d[CONF_SLAVE_ID] for d in self._devices}
            if slave_id in existing_slave_ids:
                errors[CONF_SLAVE_ID] = "duplicate_slave_id"
            else:
                self._new_device = {
                    CONF_DEVICE_ID: str(uuid.uuid4()),
                    CONF_DEVICE_NAME: user_input[CONF_DEVICE_NAME],
                    CONF_SLAVE_ID: slave_id,
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                }
                return await self.async_step_choose_definition()

        return self.async_show_form(
            step_id="add_device",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_NAME): str,
                    vol.Required(CONF_SLAVE_ID, default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                    vol.Required(CONF_SCAN_INTERVAL, default=bus_default): vol.All(
                        vol.Coerce(float), vol.Range(min=0.5, max=3600)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_choose_definition(self, user_input: dict | None = None) -> FlowResult:
        """Step: choose built-in definition, user library, or paste custom YAML."""
        if user_input is not None:
            self._new_device[CONF_DEFINITION_SOURCE] = user_input[CONF_DEFINITION_SOURCE]
            source = user_input[CONF_DEFINITION_SOURCE]
            if source == CONF_DEFINITION_BUILTIN:
                return await self.async_step_select_builtin()
            if source == CONF_DEFINITION_USER:
                return await self.async_step_select_user()
            return await self.async_step_upload_custom()

        user_defs = await self.hass.async_add_executor_job(
            _load_user_definitions, self.hass.config.config_dir
        )
        options: dict[str, str] = {CONF_DEFINITION_BUILTIN: "Built-in device library"}
        if user_defs:
            options[CONF_DEFINITION_USER] = f"User library ({len(user_defs)} definitions in /config/modbus_manager/)"
        options[CONF_DEFINITION_CUSTOM] = "Paste YAML definition"

        return self.async_show_form(
            step_id="choose_definition",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEFINITION_SOURCE, default=CONF_DEFINITION_BUILTIN): vol.In(options)
                }
            ),
        )

    async def async_step_select_builtin(self, user_input: dict | None = None) -> FlowResult:
        """Step: pick from built-in device definitions."""
        builtin = await self.hass.async_add_executor_job(_load_builtin_definitions)

        if not builtin:
            return self.async_abort(reason="no_builtin_definitions")

        if user_input is not None:
            stem = user_input[CONF_DEFINITION_FILE]
            definition = await self.hass.async_add_executor_job(_load_definition, stem)
            if definition is None:
                return self.async_abort(reason="definition_not_found")
            self._new_device[CONF_DEFINITION] = definition
            self._new_device[CONF_DEFINITION_FILE] = stem
            if definition.get("parameters"):
                return await self.async_step_device_params()
            self._devices.append(self._new_device)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="select_builtin",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEFINITION_FILE): vol.In(builtin)}
            ),
        )

    async def async_step_select_user(self, user_input: dict | None = None) -> FlowResult:
        """Step: pick from user YAML definitions in config dir."""
        config_dir = self.hass.config.config_dir
        user_defs = await self.hass.async_add_executor_job(_load_user_definitions, config_dir)

        if not user_defs:
            return self.async_abort(reason="no_user_definitions")

        if user_input is not None:
            stem = user_input[CONF_DEFINITION_USER_FILE]
            definition = await self.hass.async_add_executor_job(_load_user_definition, config_dir, stem)
            if definition is None:
                return self.async_abort(reason="definition_not_found")
            self._new_device[CONF_DEFINITION] = definition
            self._new_device[CONF_DEFINITION_USER_FILE] = stem
            if definition.get("parameters"):
                return await self.async_step_device_params()
            self._devices.append(self._new_device)
            return await self.async_step_init()

        return self.async_show_form(
            step_id="select_user",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEFINITION_USER_FILE): vol.In(user_defs)}
            ),
        )

    async def async_step_device_params(self, user_input: dict | None = None) -> FlowResult:
        """Step: fill in device-specific parameters declared in the definition."""
        parameters: dict = self._new_device[CONF_DEFINITION].get("parameters", {})

        if user_input is not None:
            self._new_device[CONF_DEVICE_PARAMS] = {k: float(v) for k, v in user_input.items()}
            self._devices.append(self._new_device)
            return await self.async_step_init()

        schema_dict: dict = {}
        params_info_lines: list[str] = []
        for param_id, param_def in parameters.items():
            default = param_def.get("default", 0)
            min_val = param_def.get("min")
            max_val = param_def.get("max")
            constraints = [vol.Coerce(float)]
            range_kwargs: dict = {}
            if min_val is not None:
                range_kwargs["min"] = float(min_val)
            if max_val is not None:
                range_kwargs["max"] = float(max_val)
            if range_kwargs:
                constraints.append(vol.Range(**range_kwargs))
            schema_dict[vol.Required(param_id, default=default)] = vol.All(*constraints)

            unit = param_def.get("unit", "")
            desc = param_def.get("description", "")
            line = f"**{param_def.get('name', param_id)}**"
            if unit:
                line += f" [{unit}]"
            if desc:
                line += f" — {desc}"
            params_info_lines.append(line)

        return self.async_show_form(
            step_id="device_params",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={
                "device_name": self._new_device.get(CONF_DEVICE_NAME, ""),
                "params_info": "\n".join(params_info_lines),
            },
        )

    # ── Edit device flow ──────────────────────────────────────────────────────

    async def async_step_edit_device(self, user_input: dict | None = None) -> FlowResult:
        """Step: pick a device to edit."""
        if not self._devices:
            return self.async_abort(reason="no_devices")

        device_options = {
            d[CONF_DEVICE_ID]: f"{d[CONF_DEVICE_NAME]} (slave {d[CONF_SLAVE_ID]})"
            for d in self._devices
        }

        if user_input is not None:
            self._editing_device_id = user_input[CONF_DEVICE_ID]
            return await self.async_step_edit_device_form()

        return self.async_show_form(
            step_id="edit_device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_ID): vol.In(device_options)}
            ),
        )

    async def async_step_edit_device_form(self, user_input: dict | None = None) -> FlowResult:
        """Step: edit slave ID for the chosen device."""
        device = next(
            (d for d in self._devices if d[CONF_DEVICE_ID] == self._editing_device_id), None
        )
        if device is None:
            return await self.async_step_init()

        errors: dict[str, str] = {}

        if user_input is not None:
            slave_id = user_input[CONF_SLAVE_ID]
            existing_slave_ids = {
                d[CONF_SLAVE_ID] for d in self._devices if d[CONF_DEVICE_ID] != self._editing_device_id
            }
            if slave_id in existing_slave_ids:
                errors[CONF_SLAVE_ID] = "duplicate_slave_id"
            else:
                self._devices = [
                    {**d, CONF_SLAVE_ID: slave_id, CONF_DEVICE_ENABLED: user_input[CONF_DEVICE_ENABLED]}
                    if d[CONF_DEVICE_ID] == self._editing_device_id
                    else d
                    for d in self._devices
                ]
                return await self.async_step_init()

        return self.async_show_form(
            step_id="edit_device_form",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SLAVE_ID, default=device[CONF_SLAVE_ID]): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=247)
                    ),
                    vol.Required(CONF_DEVICE_ENABLED, default=device.get(CONF_DEVICE_ENABLED, True)): bool,
                }
            ),
            description_placeholders={"device_name": device[CONF_DEVICE_NAME]},
            errors=errors,
        )

    async def async_step_upload_custom(self, user_input: dict | None = None) -> FlowResult:
        """Step: paste custom YAML definition and save it to config dir."""
        errors: dict[str, str] = {}
        config_dir = self.hass.config.config_dir

        if user_input is not None:
            yaml_text = user_input[CONF_DEFINITION_YAML]
            try:
                definition = yaml.safe_load(yaml_text)
                if not isinstance(definition, dict) or "entities" not in definition:
                    errors[CONF_DEFINITION_YAML] = "invalid_definition"
                else:
                    device_name = self._new_device.get(CONF_DEVICE_NAME, "custom_device")
                    base_stem = _slugify(definition.get("name", device_name))
                    stem = await self.hass.async_add_executor_job(_unique_stem, config_dir, base_stem)
                    await self.hass.async_add_executor_job(_save_user_definition, config_dir, stem, yaml_text)
                    self._new_device[CONF_DEFINITION] = definition
                    self._new_device[CONF_DEFINITION_USER_FILE] = stem
                    if definition.get("parameters"):
                        return await self.async_step_device_params()
                    self._devices.append(self._new_device)
                    return await self.async_step_init()
            except yaml.YAMLError:
                errors[CONF_DEFINITION_YAML] = "invalid_yaml"

        return self.async_show_form(
            step_id="upload_custom",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEFINITION_YAML): str,
                }
            ),
            errors=errors,
            description_placeholders={"example": "name: My Device\nentities:\n  - id: ..."},
        )

    # ── Remove device flow ────────────────────────────────────────────────────

    async def async_step_remove_device(self, user_input: dict | None = None) -> FlowResult:
        """Step: pick a device to remove."""
        if not self._devices:
            return self.async_abort(reason="no_devices")

        device_options = {
            d[CONF_DEVICE_ID]: f"{d[CONF_DEVICE_NAME]} (slave {d[CONF_SLAVE_ID]})"
            for d in self._devices
        }

        if user_input is not None:
            remove_id = user_input[CONF_DEVICE_ID]
            self._devices = [d for d in self._devices if d[CONF_DEVICE_ID] != remove_id]
            return self.async_create_entry(data={CONF_DEVICES: self._devices})

        return self.async_show_form(
            step_id="remove_device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DEVICE_ID): vol.In(device_options)}
            ),
        )
