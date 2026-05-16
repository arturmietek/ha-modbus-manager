# Modbus Manager — Home Assistant Custom Integration

Native HA integration for Modbus RTU (RS-485) and TCP buses. Replaces modbus@mqtt Docker addon with a pure-Python custom_component.

## Architecture

```
ConfigEntry (1 per bus)
└── ModbusManagerCoordinator   ← pymodbus async client, polls all devices
    └── per device_id: {entity_id: value, ...}
        ├── sensor.py          ← sensor + string entities
        ├── binary_sensor.py   ← coil / discrete_input
        ├── switch.py          ← writable coil
        └── cover.py           ← gate / barrier controller
```

Each Config Entry represents **one Modbus bus** (RTU or TCP). Multiple devices (slaves) are added per bus via the Options Flow.

### Key files

| File | Purpose |
|------|---------|
| `coordinator.py` | Polling loop, register batching, decode, write operations |
| `entity_base.py` | Shared base class (unique_id, device_info, availability) |
| `config_flow.py` | UI wizard: add bus → add devices |
| `const.py` | All string constants |
| `device_definitions/*.yaml` | Built-in device libraries |

## Device Definition YAML

Each device is described by a YAML file. Required fields per entity:

```yaml
- id: unique_entity_id        # used as entity_id suffix
  name: "Human Name"
  register_type: input | holding | coil | discrete_input
  address: 0
  entity_type: sensor | binary_sensor | switch | cover
  data_type: UINT16 | INT16 | INT32 | UINT32 | FLOAT32 | INT64 | STRING
  byte_order: BIG | LITTLE | BIG_SWAP | LITTLE_SWAP
  scale: 0.01                 # raw × scale = displayed value
  offset: 0                   # added after scale
  unit: "V"
  device_class: voltage        # HA device class
  state_class: measurement | total_increasing
  precision: 2                 # decimal places
  entity_category: config | diagnostic   # omit for primary entities
  readonly: true               # suppresses write UI (sensor only)
  value_map:                   # translate raw int/bool to string
    0: "Off"
    1: "On"
```

### Validation (optional, guards against garbage readings)

Particularly useful for PV inverters that return nonsensical values during startup or partial cloud cover, which would corrupt HA Energy dashboard `total_increasing` counters.

```yaml
- id: daily_energy
  ...
  validation:
    min: 0.0          # reject negative values
    max: 30.0         # reject values above physical maximum [same unit as scale output]
    max_delta: 5.0    # reject if change from last valid value exceeds this per poll
```

Rules are checked in order: `min` → `max` → `max_delta`. First failure wins.

On failure the coordinator returns the **last known-good value** (entity stays at its previous state, no spike visible in HA). If no previous value exists yet (first read after HA restart), the entity is marked unavailable until a valid reading arrives.

All failures are logged at `DEBUG` level — no log spam.

### Polling hints (optional, for quirky devices)

Some devices require reading a fixed block size regardless of how many entities are defined:

```yaml
polling:
  coils:
    start_address: 0
    count: 8          # forces read of 8 coils even if fewer entities
  discrete_inputs:
    start_address: 0
    count: 8
```

Without hints the coordinator auto-groups contiguous addresses into minimal read ranges.

## Entity Categories

| Category | When to use | Examples |
|----------|-------------|---------|
| *(none)* | Primary measurements shown on device card | voltage, current, power, energy |
| `diagnostic` | Operational state, less important metrics | serial number, software version, demand peaks |
| `config` | Device configuration / calibration | baud rate, slave ID, correction factors |

## Built-in Devices

| File | Device | Notes |
|------|--------|-------|
| `shenzen_lc_relay_input_board.yaml` | 8-relay + 8-DI board | polling hints required (reads all 8 at once) |
| `modbus_gate_controller.yaml` | Gate/barrier controller | cover entity, single COIL_RELAY for all commands |
| `eastron_sdm120m.yaml` | Eastron SDM120-M | single-phase energy meter, FLOAT32 registers |
| `eastron_sdm630_modbus.yaml` | Eastron SDM630 | three-phase energy meter, unverified |
| `eletechsup_r4ivb02.yaml` | Eletechsup R4IVB02 | 2-channel 4–20 mA current acquisition |
| `eletechsup_r4cva02.yaml` | Eletechsup R4CVA02 | 2-channel 0–10 V voltage acquisition |
| `eletechsup_n4aia04.yaml` | Eletechsup N4AIA04 | 4-channel (2× voltage + 2× current), writable ratios; used for rain barrel |
| `sofarsolar_ktl_x.yaml` | SofarSolar KTL-X | 3-phase string inverter, dual MPPT; `rated_power_kw` parameter required |
| `sofarsolar_tl_g3.yaml` | SofarSolar TL-G3 | single-phase string inverter, single MPPT; `rated_power_kw` parameter required |

## Device Availability

The coordinator tracks consecutive failures per device using `_failure_counts`. Behaviour:

- **Failures 1 … N-1**: `DEBUG` only — silent, covers transient outages (passing cloud, dawn startup delay)
- **Failure N** (`offline_warn_threshold`, default 3): `WARNING` logged once
- **Failures N+1 …**: `DEBUG` only — no repeated spam while device stays offline
- **Recovery**: `INFO` "device back online", failure count cleared; next transient starts fresh

Default threshold of 3 means ~90 s silence before a warning (at 30 s scan interval). Override per bus in config: `offline_warn_threshold: 5` for PV inverters that may flicker on/off with cloud cover or vary start time by season.

Connection loss to the entire bus raises `UpdateFailed` and marks all entities unavailable via `last_update_success`.

## Publication checklist

### Blocking — must be done before first release

- [ ] **GitHub repository** — HACS requires a public repo; without it the integration cannot be installed via HACS
- [ ] **`manifest.json`** — add real `documentation` and `issue_tracker` URLs once repo exists; fill `codeowners` with your GitHub handle (`["@your-nick"]`)
- [ ] **`text.py`** — entities with `data_type: STRING` are silently ignored (no platform handles them); serial numbers and firmware versions show as unavailable
- [ ] **GitHub Actions** — two workflows needed:
  - `validate.yml` — runs `hacs-action` on every push/PR (HACS requirement)
  - `release.yml` — creates a GitHub Release with integration ZIP on version tag

### Important — not blocking, but needed before wider use

- [ ] **Unit tests** — `_decode_registers`, `_apply_value_map`, `_eval_param_expr`, `_validate_and_track` are pure functions; without tests accepting external PRs is risky
- [ ] **`number.py` multi-register writes** — FLOAT32/INT32 holding registers (e.g. SDM120 config) look writable but only UINT16/INT16 actually works
- [ ] **Custom YAML upload** — the options flow step exists but is not yet implemented (stub only)
- [ ] **Edit device** — changing slave ID or swapping definition requires remove + re-add
- [ ] **Per-entity `scan_interval`** — config registers (baud rate, slave ID) poll at the same rate as measurements

### Sync reminder

> `strings.json` and `translations/en.json` must always be identical.
> When editing one, copy to the other. HA tooling validates against `strings.json`;
> the runtime uses `translations/`.

---

## Known Limitations / TODO

### Missing platforms
- **`number.py`** — writable holding register as `number` entity (calibration values, timing registers). Currently writeable holding registers silently fall back to read-only sensor.
- **`text.py`** — STRING data type entities. Currently parsed but no dedicated platform; should use `text` or `sensor` with `state_class=None`.

### Polling
- **Per-entity scan_interval** — config registers (baud rate, slave ID) poll as often as measurements. Should support a `scan_interval` override per entity or group.
- **Auto-reconnect backoff** — on repeated bus-level connection failures the coordinator retries every scan interval with no backoff.

### Config flow
- **Custom YAML upload** — Options Flow has a placeholder for user-supplied device YAML files, but the file-upload step is not yet implemented.
- **Edit device** — there is no way to change slave_id or swap device definition after adding a device; requires removing and re-adding.

### Register write safety
- `async_write_register` writes a raw uint16; no range validation, no confirmation dialog.
- Multi-register writes (INT32, FLOAT32) not yet implemented — only single uint16.

### Testing
- No unit tests yet. Core logic to test: `_decode_registers`, `_apply_value_map`, `_read_register_entities` batching.
- Integration test against real hardware: use `scripts/modbus_scan.py` (if written) or `pymodbus` REPL.

### Pending device definitions
- **SHT20** (temperature + humidity, RS-485) — device files in `devices/SHT20/`. Known issue: generates bus errors in practice (CRC problems or timing incompatibility with other devices on the same RS-485 line). Do not add until root cause is understood. PDF documentation available locally.

### HACS
- Repository not yet submitted to HACS default list.
- `hacs.json` not created.
- GitHub Actions validation workflow missing.

## Development Notes

### pymodbus 3.11.2 API (HA bundled version)

All read/write calls use keyword-only `count=` and `device_id=`:

```python
await client.read_coils(start, count=count, device_id=slave_id)
await client.read_holding_registers(start, count=count, device_id=slave_id)
await client.write_coil(address, value, device_id=slave_id)
await client.write_register(address, value, device_id=slave_id)
```

Do **not** use `slave=`, `slave_id=`, or positional args for count — they do not exist in 3.11.2.

### Adding a new device definition

1. Create `device_definitions/<manufacturer>_<model>.yaml`
2. Follow the entity schema above
3. Restart HA — the file is auto-discovered by config_flow `_load_builtin_definitions()`
4. Add a `devices/<manufacturer-model>/README.md` with register map notes and any quirks

### value_map matching order

1. Exact Python equality (`True`, `False`, `2`, `2.0`)
2. `int(value)` lookup
3. `str(int(value))` lookup (handles YAML string keys like `"2"`)
