"""Modbus Manager — native HA integration for Modbus RTU/TCP devices."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import (
    DOMAIN,
    PLATFORMS,
    CONF_DEVICES,
    CONF_DEVICE_ID,
    CONF_DEFINITION,
    CONF_DEFINITION_FILE,
    CONF_DEFINITION_USER_FILE,
    CONF_TIMEOUT,
    CONF_RETRIES,
    DEFAULT_TIMEOUT,
    DEFAULT_RETRIES,
)
from .coordinator import ModbusManagerCoordinator
from .config_flow import _load_definition, _load_user_definition

_LOGGER = logging.getLogger(__name__)

# Stored defaults from earlier versions — used by async_migrate_entry to tell "user
# never touched this" apart from a deliberate value before overwriting it.
_V1_DEFAULT_TIMEOUT = 3
_V2_DEFAULT_RETRIES = 0


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate a config entry to the current version.

    v1 -> v2: entries created before the timeout/retries tuning (see const.py) never
    stored a `retries` key and had `timeout` defaulted to 3s. Add the then-new default
    retries=0, and bump timeout to the new default only if it's still at the old
    default — a deliberately customized timeout is left untouched.

    v2 -> v3: retries=0 proved too fragile against routine RS485 noise in practice
    (see const.py DEFAULT_RETRIES comment) — bump to the new default of 1, again only
    if the entry is still at the previous default.
    """
    if entry.version == 1:
        new_data = dict(entry.data)
        if new_data.get(CONF_TIMEOUT) == _V1_DEFAULT_TIMEOUT:
            new_data[CONF_TIMEOUT] = DEFAULT_TIMEOUT
        new_data.setdefault(CONF_RETRIES, _V2_DEFAULT_RETRIES)
        hass.config_entries.async_update_entry(entry, data=new_data, version=2)
        _LOGGER.info("Migrated Modbus Manager config entry %s from v1 to v2", entry.entry_id)

    if entry.version == 2:
        new_data = dict(entry.data)
        if new_data.get(CONF_RETRIES) == _V2_DEFAULT_RETRIES:
            new_data[CONF_RETRIES] = DEFAULT_RETRIES
        hass.config_entries.async_update_entry(entry, data=new_data, version=3)
        _LOGGER.info("Migrated Modbus Manager config entry %s from v2 to v3", entry.entry_id)

    return True


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
