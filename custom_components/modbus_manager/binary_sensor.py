"""Binary sensor platform — discrete inputs (read-only bits)."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_DEFINITION, ENTITY_TYPE_BINARY_SENSOR
from .coordinator import ModbusManagerCoordinator
from .entity_base import ModbusManagerEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ModbusManagerCoordinator = hass.data[DOMAIN][entry.entry_id]
    devices: list[dict] = coordinator.devices

    entities = []
    for device in devices:
        definition = device.get(CONF_DEFINITION, {})
        for entity_def in definition.get("entities", []):
            if entity_def.get("entity_type") == ENTITY_TYPE_BINARY_SENSOR:
                entities.append(ModbusManagerBinarySensor(coordinator, device, entity_def))

    async_add_entities(entities)


class ModbusManagerBinarySensor(ModbusManagerEntity, BinarySensorEntity):
    """A read-only bit from a discrete input register."""

    def __init__(self, coordinator, device_config, entity_def) -> None:
        super().__init__(coordinator, device_config, entity_def)

        device_class_str = entity_def.get("device_class")
        if device_class_str:
            try:
                self._attr_device_class = BinarySensorDeviceClass(device_class_str)
            except ValueError:
                self._attr_device_class = None

    @property
    def is_on(self) -> bool | None:
        val = self._entity_value
        if val is None:
            return None
        return bool(val)
