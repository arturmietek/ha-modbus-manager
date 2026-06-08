"""Switch platform — coil outputs (read/write bits)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_DEFINITION, ENTITY_TYPE_SWITCH
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
            if entity_def.get("entity_type") == ENTITY_TYPE_SWITCH:
                entities.append(ModbusManagerSwitch(coordinator, device, entity_def))

    async_add_entities(entities)


class ModbusManagerSwitch(ModbusManagerEntity, SwitchEntity):
    """A coil register exposed as a switch."""

    def __init__(self, coordinator, device_config, entity_def) -> None:
        super().__init__(coordinator, device_config, entity_def)
        self._attr_device_class = SwitchDeviceClass.SWITCH
        self._address: int = entity_def["address"]

    @property
    def is_on(self) -> bool | None:
        val = self._entity_value
        if val is None:
            return None
        return bool(val)

    async def async_turn_on(self, **kwargs) -> None:
        success = await self.coordinator.async_write_coil(self._slave_id, self._address, True)
        if success:
            await self.coordinator.async_force_refresh_device(self._device_config["device_id"])

    async def async_turn_off(self, **kwargs) -> None:
        success = await self.coordinator.async_write_coil(self._slave_id, self._address, False)
        if success:
            await self.coordinator.async_force_refresh_device(self._device_config["device_id"])
