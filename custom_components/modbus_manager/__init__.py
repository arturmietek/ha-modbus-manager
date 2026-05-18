"""Modbus Manager — native HA integration for Modbus RTU/TCP devices."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN, PLATFORMS, CONF_DEVICES, CONF_DEVICE_ID, CONF_DEFINITION, CONF_DEFINITION_FILE, CONF_DEFINITION_USER_FILE
from .coordinator import ModbusManagerCoordinator
from .config_flow import _load_definition, _load_user_definition

_LOGGER = logging.getLogger(__name__)


def _refresh_device_definitions(config_dir: str, devices: list[dict]) -> list[dict]:
    """Reload YAML definitions from disk so edits take effect on restart."""
    refreshed = []
    for device in devices:
        stem = device.get(CONF_DEFINITION_FILE)
        if stem:
            fresh = _load_definition(stem)
            if fresh is not None:
                device = {**device, CONF_DEFINITION: fresh}
            else:
                fresh = _load_user_definition(config_dir, stem)
                if fresh is not None:
                    _LOGGER.info(
                        "Built-in definition '%s.yaml' not found — loaded from config dir", stem
                    )
                    device = {**device, CONF_DEFINITION: fresh, CONF_DEFINITION_USER_FILE: stem}
                else:
                    _LOGGER.warning(
                        "Definition '%s.yaml' not found in built-in library or config dir — using stored copy", stem
                    )
        user_stem = device.get(CONF_DEFINITION_USER_FILE)
        if user_stem:
            fresh = _load_user_definition(config_dir, user_stem)
            if fresh is not None:
                device = {**device, CONF_DEFINITION: fresh}
            else:
                _LOGGER.warning(
                    "User definition '%s.yaml' not found in config dir — using stored copy", user_stem
                )
        refreshed.append(device)
    return refreshed


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Modbus bus from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    raw_devices: list[dict] = entry.options.get(CONF_DEVICES, [])
    devices = await hass.async_add_executor_job(_refresh_device_definitions, hass.config.config_dir, raw_devices)

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

    # Remove entities and devices from HA registry that belong to devices no
    # longer present in options (e.g. after user removes a device).
    current_device_ids = {d[CONF_DEVICE_ID] for d in devices}
    _cleanup_orphaned_registry_entries(hass, entry, current_device_ids)

    # Re-setup entities when options change (device added/removed)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


def _cleanup_orphaned_registry_entries(
    hass: HomeAssistant, entry: ConfigEntry, current_device_ids: set[str]
) -> None:
    """Remove entity and device registry entries for devices no longer in options."""
    prefix = entry.entry_id + "_"

    entity_reg = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(entity_reg, entry.entry_id):
        uid = entity_entry.unique_id
        if uid.startswith(prefix):
            # unique_id format: "{entry_id}_{device_id}_{entity_id}"
            remainder = uid[len(prefix):]
            if not any(remainder.startswith(did + "_") for did in current_device_ids):
                _LOGGER.debug("Removing orphaned entity %s (unique_id: %s)", entity_entry.entity_id, uid)
                entity_reg.async_remove(entity_entry.entity_id)

    device_reg = dr.async_get(hass)
    for device_entry in dr.async_entries_for_config_entry(device_reg, entry.entry_id):
        for domain, identifier in device_entry.identifiers:
            if domain == DOMAIN and identifier.startswith(prefix):
                # identifier format: "{entry_id}_{device_id}"
                device_id = identifier[len(prefix):]
                if device_id not in current_device_ids:
                    _LOGGER.debug("Removing orphaned device %s (device_id: %s)", device_entry.id, device_id)
                    device_reg.async_remove_device(device_entry.id)
                break


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
