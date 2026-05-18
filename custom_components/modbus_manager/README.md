# Modbus Manager — Developer Reference

Internal architecture notes for contributors.
User documentation is in [the root README](../../README.md) and [docs/](../../docs/).

## Architecture

```
ConfigEntry (1 per bus)
└── ModbusManagerCoordinator   ← pymodbus async client, polls all devices
    └── per device_id: {entity_id: (raw_regs, decoded_value), ...}
        ├── sensor.py          ← sensor + string entities
        ├── binary_sensor.py   ← coil / discrete_input
        ├── switch.py          ← writable coil
        ├── number.py          ← writable holding register
        └── cover.py           ← gate / barrier controller
```

Each Config Entry represents **one Modbus bus** (RTU or TCP). Multiple devices (slaves) are added per bus via the Options Flow.

## Key files

| File | Purpose |
|------|---------|
| `coordinator.py` | Polling loop, register batching, decode, write operations |
| `entity_base.py` | Shared base class (unique_id, device_info, availability) |
| `config_flow.py` | UI wizard: add bus → add devices |
| `const.py` | All string constants |
| `modbus_device/` | Shared decoder library (also used by CLI monitor) |
| `device_definitions/*.yaml` | Built-in device definitions |

## Device definition storage

Device options are stored in `ConfigEntry.options[CONF_DEVICES]` — a list of dicts, one per slave. Each dict contains:

| Key | Description |
|-----|-------------|
| `CONF_DEVICE_ID` | UUID, stable across reloads |
| `CONF_DEVICE_NAME` | Display name |
| `CONF_SLAVE_ID` | Modbus slave/unit ID |
| `CONF_SCAN_INTERVAL` | Poll interval in seconds |
| `CONF_DEFINITION` | Parsed YAML dict (cached copy) |
| `CONF_DEFINITION_FILE` | Stem of built-in YAML file, if from built-in library |
| `CONF_DEFINITION_USER_FILE` | Stem of user YAML file in `/config/modbus_manager/`, if from user library |

On `async_setup_entry`, `_refresh_device_definitions` reloads from disk (built-in or user dir) so YAML edits take effect on restart without re-adding devices.

## pymodbus 3.11.2 API (HA bundled version)

All read/write calls use keyword-only `count=` and `device_id=`:

```python
await client.read_coils(start, count=count, device_id=slave_id)
await client.read_holding_registers(start, count=count, device_id=slave_id)
await client.write_coil(address, value, device_id=slave_id)
await client.write_register(address, value, device_id=slave_id)
```

Do **not** use `slave=` or positional args for count.

## Device availability

The coordinator tracks consecutive failures per device using `_failure_counts`:

- **Failures 1 … N-1**: `DEBUG` only — silent, covers transient outages
- **Failure N** (`offline_warn_threshold`, default 3): `WARNING` logged once
- **Failures N+1 …**: `DEBUG` only — no repeated spam
- **Recovery**: `INFO` "device back online", failure count cleared

Default threshold of 3 → ~90 s silence before a warning at 30 s scan interval.

## Entity and device registry cleanup

When a device is removed from options, `_cleanup_orphaned_registry_entries` in `__init__.py` explicitly removes its entity and device registry entries. This must be called after `async_forward_entry_setups` because HA does not clean up registry entries automatically on reload.

- Entity unique_id format: `{entry_id}_{device_id}_{entity_id}`
- Device identifier format: `(DOMAIN, "{entry_id}_{device_id}")`

## strings.json / translations sync

`strings.json` and `translations/en.json` must always be identical.
When editing one, copy to the other. HA tooling validates against `strings.json`; the runtime uses `translations/`.

## Known limitations

- **Multi-register writes** — only UINT16/INT16 single-register writes implemented. FLOAT32/INT32 holding register writes silently fail.
- **Per-entity scan_interval** — all entities on a device poll at the same rate.
- **Edit device** — only slave ID is editable after adding. Device name, scan interval, and definition are fixed; requires remove + re-add to change them.
- **SHT20** — known bus errors (CRC/timing issues with other devices on the same RS-485 line). Do not add until root cause understood.
