"""Sensor platform — numeric and text register values."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfElectricCurrent,
    UnitOfPower,
    UnitOfEnergy,
    UnitOfApparentPower,
    UnitOfReactivePower,
    UnitOfTemperature,
    UnitOfFrequency,
    UnitOfTime,
    PERCENTAGE,
)

from .const import DOMAIN, CONF_DEFINITION, ENTITY_TYPE_SENSOR, ENTITY_TYPE_TEXT
from .coordinator import ModbusManagerCoordinator
from .entity_base import ModbusManagerEntity

# Map unit strings from YAML to HA unit constants
UNIT_MAP: dict[str, str] = {
    "V": UnitOfElectricPotential.VOLT,
    "mV": UnitOfElectricPotential.MILLIVOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "mA": UnitOfElectricCurrent.MILLIAMPERE,
    "W": UnitOfPower.WATT,
    "kW": UnitOfPower.KILO_WATT,
    "VA": UnitOfApparentPower.VOLT_AMPERE,
    "kVA": UnitOfApparentPower.KILO_VOLT_AMPERE,
    "var": UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
    "kvar": UnitOfReactivePower.KILO_VOLT_AMPERE_REACTIVE,
    "Wh": UnitOfEnergy.WATT_HOUR,
    "kWh": UnitOfEnergy.KILO_WATT_HOUR,
    "°C": UnitOfTemperature.CELSIUS,
    "°F": UnitOfTemperature.FAHRENHEIT,
    "Hz": UnitOfFrequency.HERTZ,
    "s": UnitOfTime.SECONDS,
    "min": UnitOfTime.MINUTES,
    "h": UnitOfTime.HOURS,
    "ms": UnitOfTime.MILLISECONDS,
    "%": PERCENTAGE,
}


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
            if entity_def.get("entity_type") in (ENTITY_TYPE_SENSOR, ENTITY_TYPE_TEXT):
                entities.append(ModbusManagerSensor(coordinator, device, entity_def))

    async_add_entities(entities)


class ModbusManagerSensor(ModbusManagerEntity, SensorEntity):
    """A holding/input register value exposed as a sensor."""

    def __init__(self, coordinator, device_config, entity_def) -> None:
        super().__init__(coordinator, device_config, entity_def)

        # Device class
        device_class_str = entity_def.get("device_class")
        if device_class_str:
            try:
                self._attr_device_class = SensorDeviceClass(device_class_str)
            except ValueError:
                self._attr_device_class = None

        # State class
        is_text = entity_def.get("entity_type") == ENTITY_TYPE_TEXT
        state_class_str = entity_def.get("state_class")

        if is_text:
            self._attr_state_class = None
        elif state_class_str:
            try:
                self._attr_state_class = SensorStateClass(state_class_str)
            except ValueError:
                self._attr_state_class = None
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

        # value_map produces strings — HA forbids numeric state_class for non-numeric values.
        # Override unconditionally: this must come after the block above.
        if entity_def.get("value_map"):
            self._attr_state_class = None

        # Unit of measurement
        unit_raw = entity_def.get("unit")
        if unit_raw:
            self._attr_native_unit_of_measurement = UNIT_MAP.get(unit_raw, unit_raw)

        # Precision for display
        precision = entity_def.get("precision")
        if precision is not None:
            self._attr_suggested_display_precision = int(precision)

        # HA forbids EntityCategory.CONFIG on sensors — downgrade silently to DIAGNOSTIC
        from homeassistant.helpers.entity import EntityCategory
        if getattr(self, "_attr_entity_category", None) == EntityCategory.CONFIG:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return self._entity_value
