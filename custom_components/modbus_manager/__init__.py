"""Modbus Manager — native HA integration for Modbus RTU/TCP devices."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS, CONF_DEVICES, CONF_DEFINITION, CONF_DEFINITION_FILE
from .coordinator import ModbusManagerCoordinator
from .config_flow import _load_definition

_LOGGER = logging.getLogger(__name__)


def _refresh_device_definitions(devices: list[dict]) -> list[dict]:
    """Reload built-in YAML definitions from disk so YAML edits take effect on restart.

    Devices added from a built-in file have CONF_DEFINITION_FILE set.
    Custom-YAML devices have no file reference and keep their stored definition.
    """
    refreshed = []
    for device in devices:
        stem = device.get(CONF_DEFINITION_FILE)
        if stem:
            fresh = _load_definition(stem)
            if fresh is not None:
                device = {**device, CONF_DEFINITION: fresh}
            else:
                _LOGGER.warning(
                    "Built-in definition file '%s.yaml' not found — using stored copy", stem
                )
        refreshed.append(device)
    return refreshed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Modbus bus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    raw_devices: list[dict] = entry.options.get(CONF_DEVICES, [])
    devices = await hass.async_add_executor_job(_refresh_device_definitions, raw_devices)

    coordinator = ModbusManagerCoordinator(
        hass=hass,
        bus_config=dict(entry.data),
        devices=devices,  # definitions already refreshed from disk
    )
    # Store coordinator reference so entity platforms can retrieve it
    coordinator.config_entry = entry

    # Attempt initial connection
    connected = await coordinator.async_connect()
    if not connected:
        raise ConfigEntryNotReady("Cannot connect to Modbus bus")

    # First data fetch
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Set up all entity platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Re-setup entities when options change (device added/removed)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unloaded:
        coordinator: ModbusManagerCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_disconnect()

    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options are updated (device added/removed)."""
    await hass.config_entries.async_reload(entry.entry_id)
