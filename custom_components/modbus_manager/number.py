"""Number platform for Modbus Manager — writable holding registers."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DOMAIN,
    CONF_DEVICE_ID,
    CONF_SLAVE_ID,
    CONF_DEFINITION,
    CONF_DEVICE_NAME,
    ENTITY_TYPE_NUMBER,
    DATA_TYPE_INT16,
    DATA_TYPE_UINT16,
)
from .coordinator import ModbusManagerCoordinator
from .entity_base import ModbusManagerEntity

_LOGGER = logging.getLogger(__name__)

_UINT16_MAX = 65535
_INT16_MIN = -32768
_INT16_MAX = 32767


def _to_raw(display_value: float, scale: float, offset: float, data_type: str) -> int | None:
    """Convert a scaled display value back to a raw register integer.

    Returns None when the result falls outside the valid range for data_type.
    Negative INT16 values are encoded as two's-complement UINT16.
    """
    raw = round((display_value - offset) / scale)

    if data_type == DATA_TYPE_UINT16:
        if 0 <= raw <= _UINT16_MAX:
            return raw
        return None

    if data_type == DATA_TYPE_INT16:
        if _INT16_MIN <= raw <= _INT16_MAX:
            return raw if raw >= 0 else raw + 0x10000
        return None

    # Fallback for unknown types: treat as UINT16
    if 0 <= raw <= _UINT16_MAX:
        return raw
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ModbusManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[ModbusManagerNumber] = []

    for device in coordinator.devices:
        definition = device[CONF_DEFINITION]
        device_config = {
            "device_id": device[CONF_DEVICE_ID],
            "device_name": device.get(CONF_DEVICE_NAME, device[CONF_DEVICE_ID]),
            "slave_id": device[CONF_SLAVE_ID],
            "definition": definition,
        }
        for entity_def in definition.get("entities", []):
            if entity_def.get("entity_type") == ENTITY_TYPE_NUMBER:
                entities.append(ModbusManagerNumber(coordinator, device_config, entity_def))

    async_add_entities(entities)


class ModbusManagerNumber(ModbusManagerEntity, NumberEntity, RestoreEntity):
    """A writable numeric holding register."""

    def __init__(
        self,
        coordinator: ModbusManagerCoordinator,
        device_config: dict,
        entity_def: dict,
    ) -> None:
        super().__init__(coordinator, device_config, entity_def)

        self._scale: float = entity_def.get("scale", 1.0)
        self._offset: float = entity_def.get("offset", 0.0)
        self._data_type: str = entity_def.get("data_type", DATA_TYPE_UINT16)

        self._attr_native_unit_of_measurement = entity_def.get("unit")

        # Displayed min/max/step are in scaled units
        self._attr_native_min_value = float(entity_def.get("min", 0))
        self._attr_native_max_value = float(entity_def.get("max", _UINT16_MAX if self._data_type == DATA_TYPE_UINT16 else _INT16_MAX))
        self._attr_native_step = float(entity_def.get("step", self._scale))

        mode_str = entity_def.get("mode", "box")
        self._attr_mode = NumberMode.SLIDER if mode_str == "slider" else NumberMode.BOX

        self._restored_value: float | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            try:
                self._restored_value = float(last_state.state)
            except (ValueError, TypeError):
                pass

    @property
    def native_value(self) -> float | None:
        raw = self._entity_value
        if raw is None:
            return self._restored_value
        try:
            return float(raw)
        except (ValueError, TypeError):
            return self._restored_value

    async def async_set_native_value(self, value: float) -> None:
        raw_int = self._to_raw(value)
        if raw_int is None:
            _LOGGER.error(
                "Cannot write %s to %s: value out of range for %s",
                value, self._entity_id_key, self._data_type,
            )
            return

        slave_id: int = self._device_config["slave_id"]
        address: int = self._entity_def["address"]

        ok = await self.coordinator.async_write_register(slave_id, address, raw_int)
        if ok:
            await self.coordinator.async_force_refresh_device(self._device_config["device_id"])
        else:
            _LOGGER.warning("Write failed for %s address %d", self._entity_id_key, address)

    def _to_raw(self, display_value: float) -> int | None:
        return _to_raw(display_value, self._scale, self._offset, self._data_type)
