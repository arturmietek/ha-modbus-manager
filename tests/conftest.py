"""Test configuration — stub HA deps and load coordinator + config_flow directly."""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).parent.parent
COMPONENT = ROOT / "custom_components" / "modbus_manager"


def _load_direct(module_name: str, file_path: Path) -> types.ModuleType:
    """Import a .py file as *module_name* without triggering package __init__."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _stub(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules[name] = mod
    return mod


# ── 1. Stub homeassistant — symbols used by coordinator + config_flow ─────────

for _name in [
    "homeassistant",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.restore_state",
    "homeassistant.config_entries",
    "homeassistant.data_entry_flow",
    "homeassistant.components",
    "homeassistant.components.sensor",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.switch",
    "homeassistant.components.number",
    "homeassistant.components.cover",
    "homeassistant.const",
]:
    _stub(_name)


import enum as _enum

class _SensorStateClass(str, _enum.Enum):
    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"

class _SensorDeviceClass(str, _enum.Enum):
    ENERGY = "energy"
    POWER = "power"
    VOLTAGE = "voltage"
    CURRENT = "current"
    TEMPERATURE = "temperature"
    FREQUENCY = "frequency"
    DURATION = "duration"
    TIMESTAMP = "timestamp"

_sensor_mod = sys.modules["homeassistant.components.sensor"]
_sensor_mod.SensorStateClass = _SensorStateClass
_sensor_mod.SensorDeviceClass = _SensorDeviceClass
_sensor_mod.SensorEntity = object

_bsensor_mod = sys.modules["homeassistant.components.binary_sensor"]
_bsensor_mod.BinarySensorEntity = object
_bsensor_mod.BinarySensorDeviceClass = MagicMock

_switch_mod = sys.modules["homeassistant.components.switch"]
_switch_mod.SwitchEntity = object
_switch_mod.SwitchDeviceClass = MagicMock

_number_mod = sys.modules["homeassistant.components.number"]
_number_mod.NumberEntity = object
_number_mod.NumberMode = MagicMock
sys.modules["homeassistant.helpers.restore_state"].RestoreEntity = object

_cover_mod = sys.modules["homeassistant.components.cover"]
_cover_mod.CoverEntity = object
_cover_mod.CoverDeviceClass = MagicMock
_cover_mod.CoverEntityFeature = MagicMock

_he = sys.modules["homeassistant.helpers.entity"]
_he.DeviceInfo = dict
_he.EntityCategory = MagicMock

_hep = sys.modules["homeassistant.helpers.entity_platform"]
_hep.AddEntitiesCallback = MagicMock

_sys_const = sys.modules["homeassistant.const"]
for _attr in [
    "UnitOfElectricPotential", "UnitOfElectricCurrent", "UnitOfPower",
    "UnitOfEnergy", "UnitOfApparentPower", "UnitOfReactivePower",
    "UnitOfTemperature", "UnitOfFrequency", "UnitOfTime", "PERCENTAGE",
]:
    setattr(_sys_const, _attr, MagicMock())


class _FakeDUC:
    """Minimal DataUpdateCoordinator stand-in."""
    def __init__(self, hass, logger, *, name, update_interval, update_method=None):
        self.data = None


_uc = sys.modules["homeassistant.helpers.update_coordinator"]
_uc.DataUpdateCoordinator = _FakeDUC
_uc.UpdateFailed = Exception
class _FakeCoordinatorEntity:
    def __init_subclass__(cls, **kwargs): super().__init_subclass__(**kwargs)
    def __class_getitem__(cls, item): return cls

_uc.CoordinatorEntity = _FakeCoordinatorEntity

_core = sys.modules["homeassistant.core"]
_core.HomeAssistant = MagicMock
_core.callback = lambda f: f  # callback is used as a decorator

class _FakeConfigFlow:
    """Minimal ConfigFlow stand-in that accepts domain= keyword in subclasses."""
    def __init_subclass__(cls, domain=None, **kwargs):
        super().__init_subclass__(**kwargs)

class _FakeOptionsFlow:
    pass

_ce = sys.modules["homeassistant.config_entries"]
_ce.ConfigFlow = _FakeConfigFlow
_ce.OptionsFlow = _FakeOptionsFlow
_ce.ConfigEntry = MagicMock

_df = sys.modules["homeassistant.data_entry_flow"]
_df.FlowResult = dict

# ── 2. Load dependency chain bottom-up (no __init__.py involved) ──────────────

_load_direct("custom_components.modbus_manager.const",
             COMPONENT / "const.py")

_load_direct("modbus_device.model",   COMPONENT / "modbus_device" / "model.py")
_load_direct("modbus_device.decoder", COMPONENT / "modbus_device" / "decoder.py")
_load_direct("modbus_device.loader",  COMPONENT / "modbus_device" / "loader.py")
_load_direct("modbus_device",         COMPONENT / "modbus_device" / "__init__.py")

# Alias so relative imports inside coordinator (.modbus_device, .const) resolve
sys.modules["custom_components.modbus_manager.modbus_device"] = sys.modules["modbus_device"]

_load_direct("custom_components.modbus_manager.coordinator",
             COMPONENT / "coordinator.py")

_load_direct("custom_components.modbus_manager.config_flow",
             COMPONENT / "config_flow.py")

_load_direct("custom_components.modbus_manager.entity_base",
             COMPONENT / "entity_base.py")

_load_direct("custom_components.modbus_manager.sensor",
             COMPONENT / "sensor.py")
