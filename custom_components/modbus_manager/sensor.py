"""Sensor platform — numeric and text register values."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory, DeviceInfo
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

from .const import DOMAIN, CONF_DEFINITION, CONF_DEVICE_ID, CONF_DEVICE_NAME, CONF_SLAVE_ID, ENTITY_TYPE_SENSOR, ENTITY_TYPE_TEXT
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


def _resolve_state_class(entity_def: dict):
    """Return SensorStateClass for an entity definition.

    Priority:
    1. Text / STRING entities → None (no numeric statistics)
    2. Explicit state_class in YAML → use it (None on unknown value)
    3. Default → MEASUREMENT
    Note: value_map / bitmask override is applied by the caller after unit wiring.
    """
    is_text = (
        entity_def.get("entity_type") == ENTITY_TYPE_TEXT
        or entity_def.get("data_type") == "STRING"
    )
    if is_text:
        return None

    state_class_str = entity_def.get("state_class")
    if state_class_str:
        try:
            return SensorStateClass(state_class_str)
        except ValueError:
            return None

    return SensorStateClass.MEASUREMENT


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
        entities.extend(_poll_stat_entities(coordinator, device))

    async_add_entities(entities)


def _poll_stat_entities(coordinator, device: dict) -> list:
    return [
        ModbusManagerPollStatSensor(coordinator, device, stat)
        for stat in (
            {
                "key": "_poll_last_success",
                "name": "Last Successful Poll",
                "device_class": SensorDeviceClass.TIMESTAMP,
                "state_class": None,
                "unit": None,
            },
            {
                "key": "_poll_error_count",
                "name": "Consecutive Poll Errors",
                "device_class": None,
                "state_class": SensorStateClass.MEASUREMENT,
                "unit": None,
            },
            {
                "key": "_poll_duration_ms",
                "name": "Last Poll Duration",
                "device_class": SensorDeviceClass.DURATION,
                "state_class": SensorStateClass.MEASUREMENT,
                "unit": "ms",
            },
        )
    ]


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
        self._attr_state_class = _resolve_state_class(entity_def)

        # value_map and bitmask produce strings — HA forbids numeric state_class for non-numeric values.
        # Override unconditionally: this must come after the block above.
        if entity_def.get("value_map") or entity_def.get("bitmask"):
            self._attr_state_class = None
            self._attr_native_unit_of_measurement = None

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


class ModbusManagerPollStatSensor(ModbusManagerEntity, SensorEntity):
    """Diagnostic sensor reporting coordinator polling statistics."""

    def __init__(self, coordinator, device_config: dict, stat: dict) -> None:
        super().__init__(coordinator, device_config, {
            "id": stat["key"],
            "name": stat["name"],
            "entity_category": "diagnostic",
        })
        self._stat_key = stat["key"]
        self._attr_device_class = stat["device_class"]
        self._attr_state_class = stat["state_class"]
        if stat["unit"]:
            self._attr_native_unit_of_measurement = UNIT_MAP.get(stat["unit"], stat["unit"])
        self._attr_entity_registry_enabled_default = False

    @property
    def native_value(self):
        device_id = self._device_config[CONF_DEVICE_ID]
        device_data = self.coordinator.data or {}
        return device_data.get(device_id, {}).get(self._stat_key)

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        device_id = self._device_config[CONF_DEVICE_ID]
        return device_id in (self.coordinator.data or {})
