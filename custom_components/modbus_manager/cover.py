"""Cover platform — gates, blinds, garage doors via Modbus."""
from __future__ import annotations

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    CONF_DEFINITION,
    CONF_SLAVE_ID,
    ENTITY_TYPE_COVER,
    REGISTER_COIL,
    REGISTER_HOLDING,
)
from .coordinator import ModbusManagerCoordinator
from .entity_base import ModbusManagerEntity

# Values that value_map should resolve to for cover state
_STATE_OPEN = "open"
_STATE_CLOSED = "closed"
_STATE_OPENING = "opening"
_STATE_CLOSING = "closing"


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
            if entity_def.get("entity_type") == ENTITY_TYPE_COVER:
                entities.append(ModbusManagerCover(coordinator, device, entity_def))

    async_add_entities(entities)


class ModbusManagerCover(ModbusManagerEntity, CoverEntity):
    """A cover entity driven by Modbus registers.

    State is read from a register (coil, discrete input, holding, or input)
    and translated via value_map to one of: open / closed / opening / closing.

    Commands (open / close / stop) write to coil or holding registers as
    defined in the 'commands' block of the entity definition.

    YAML example:
        - id: gate
          name: "Entrance Gate"
          entity_type: cover
          device_class: gate
          register_type: discrete_input
          address: 0
          value_map:
            true: "open"
            false: "closed"
          commands:
            open:
              register_type: coil
              address: 0
              value: true
            close:
              register_type: coil
              address: 1
              value: true
            stop:
              register_type: coil
              address: 2
              value: true
    """

    def __init__(self, coordinator, device_config, entity_def) -> None:
        super().__init__(coordinator, device_config, entity_def)

        device_class_str = entity_def.get("device_class", "gate")
        try:
            self._attr_device_class = CoverDeviceClass(device_class_str)
        except ValueError:
            self._attr_device_class = CoverDeviceClass.GATE

        commands: dict = entity_def.get("commands", {})
        self._commands = commands

        features = CoverEntityFeature(0)
        if "open" in commands:
            features |= CoverEntityFeature.OPEN
        if "close" in commands:
            features |= CoverEntityFeature.CLOSE
        if "stop" in commands:
            features |= CoverEntityFeature.STOP
        self._attr_supported_features = features

    @property
    def _state_str(self) -> str | None:
        val = self._entity_value
        if val is None:
            return None
        return str(val)

    @property
    def is_closed(self) -> bool | None:
        s = self._state_str
        if s is None:
            return None
        return s == _STATE_CLOSED

    @property
    def is_opening(self) -> bool:
        return self._state_str == _STATE_OPENING

    @property
    def is_closing(self) -> bool:
        return self._state_str == _STATE_CLOSING

    async def async_open_cover(self, **kwargs) -> None:
        await self._execute_command("open")

    async def async_close_cover(self, **kwargs) -> None:
        await self._execute_command("close")

    async def async_stop_cover(self, **kwargs) -> None:
        await self._execute_command("stop")

    async def _execute_command(self, command_name: str) -> None:
        cmd = self._commands.get(command_name)
        if not cmd:
            return

        reg_type = cmd.get("register_type", REGISTER_COIL)
        address: int = cmd["address"]
        value = cmd.get("value", True)

        if reg_type == REGISTER_COIL:
            await self.coordinator.async_write_coil(self._slave_id, address, bool(value))
        elif reg_type == REGISTER_HOLDING:
            await self.coordinator.async_write_register(self._slave_id, address, int(value))

        await self.coordinator.async_force_refresh_device(self._device_config["device_id"])
