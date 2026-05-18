# Device Definition YAML — Format Reference

This document describes the YAML format for Modbus Manager device definitions.
It is written to be usable directly as an AI prompt: paste it together with a device's Modbus register map to generate a working definition file.

---

## File structure

```yaml
name: "Manufacturer Model"          # display name in HA and config UI
manufacturer: "Manufacturer"
model: "Model"
version: "1.0"
description: >
  One or two sentences. Include: interface type (RTU/TCP), register format
  (FLOAT32 big-endian, UINT16, etc.), default slave ID, default baud rate.

entities:
  - ...                             # list of entity definitions (see below)

polling:                            # optional, see Polling hints
  input:
    start_address: 0
    count: 40
```

---

## Entity fields

### Required

| Field | Values | Description |
|-------|--------|-------------|
| `id` | snake_case string | Unique within file. Used as entity_id suffix. No spaces. |
| `name` | string | Human-readable label shown in HA. |
| `register_type` | `input` `holding` `coil` `discrete_input` | Modbus function code group. |
| `address` | integer | Register address (0-based). For FLOAT32/UINT32/INT32: first of the two registers. |
| `entity_type` | `sensor` `binary_sensor` `switch` `cover` `number` | HA platform. |

### Data type and byte order

| Field | Values | Default |
|-------|--------|---------|
| `data_type` | `UINT16` `INT16` `UINT32` `INT32` `FLOAT32` `INT64` `STRING` | `UINT16` |
| `byte_order` | `BIG` `LITTLE` `BIG_SWAP` `LITTLE_SWAP` | `BIG` |
| `register_count` | integer | Only for `STRING` — number of registers to read. |

**Register widths:**
- `UINT16` / `INT16` — 1 register (2 bytes)
- `UINT32` / `INT32` / `FLOAT32` — 2 registers (4 bytes)
- `INT64` — 4 registers (8 bytes)
- `STRING` — `register_count` registers, high byte then low byte per register

**Byte order for multi-register types:**
- `BIG` — standard big-endian (most Modbus devices)
- `LITTLE` — little-endian word order
- `BIG_SWAP` — big-endian words, bytes swapped within each word
- `LITTLE_SWAP` — little-endian words, bytes swapped

### Scaling and units

| Field | Type | Description |
|-------|------|-------------|
| `scale` | float | Multiply raw value. Default `1.0`. Example: `0.01` when device sends centiunits. |
| `offset` | float | Add after scale. Default `0.0`. Rarely needed. |
| `unit` | string | Physical unit string passed to HA. Must match `device_class` expectations. |
| `precision` | integer | Decimal places for display. Use `0` for integer values (serial numbers, counts). |

### HA metadata

| Field | Values | Description |
|-------|--------|-------------|
| `device_class` | see table below | HA SensorDeviceClass. Controls icon, unit validation, dashboard integration. |
| `state_class` | `measurement` `total_increasing` `total` | Required for Energy dashboard. |
| `entity_category` | `diagnostic` `config` | Omit for primary measurements. |
| `readonly` | `true` | Suppress write UI. Use for holding registers that configure the device. |

### Optional features

| Field | Description |
|-------|-------------|
| `value_map` | Dict mapping raw int/bool to display string. Applied after scale/offset. |
| `validation` | Dict with `min`, `max`, `max_delta` — rejects out-of-range readings. |

---

## Device class / state class / unit combinations

Use this table to pick correct HA metadata. HA validates the combination — wrong choices produce warnings in the log.

| Measurement | `device_class` | `state_class` | `unit` |
|-------------|---------------|---------------|--------|
| Voltage | `voltage` | `measurement` | `V` |
| Current | `current` | `measurement` | `A` |
| Active power | `power` | `measurement` | `W` or `kW` |
| Apparent power | `apparent_power` | `measurement` | `VA` or `kVA` |
| Reactive power | `reactive_power` | `measurement` | `var` or `kvar` |
| Power factor | `power_factor` | `measurement` | *(none)* — value must be −1.0…1.0 |
| Frequency | `frequency` | `measurement` | `Hz` |
| Active energy (import/export/total) | `energy` | `total_increasing` | `kWh` or `Wh` |
| Reactive energy | `reactive_energy` | `total_increasing` | `kvarh` or `varh` |
| Temperature | `temperature` | `measurement` | `°C` or `°F` |
| Humidity | `humidity` | `measurement` | `%` |
| Illuminance | `illuminance` | `measurement` | `lx` |
| Pressure | `pressure` | `measurement` | `hPa` |

**Rules:**
- `total_increasing` requires a monotonically increasing counter (energy meters, pulse counters). Never use for power (W).
- `power_factor`: omit `unit`, value must be the dimensionless ratio (−1…1), not percent.
- For non-physical values (status codes, baud rate, slave ID): omit `device_class` and `state_class`.

---

## entity_category guidelines

| Category | When to use | Examples |
|----------|-------------|---------|
| *(none)* | Primary measurements on device card | voltage, current, power, energy totals |
| `diagnostic` | Operational detail, less important metrics | serial number, firmware version, demand peaks, reactive energy |
| `config` | Device configuration registers | baud rate, slave ID, measurement mode |

---

## value_map

Translate raw integer or boolean values to human-readable strings. Applied after `scale`/`offset`.

```yaml
value_map:
  0: "2400 bps"
  1: "4800 bps"
  2: "9600 bps"
```

For coils/discrete inputs the raw value is a Python bool (`True`/`False`). Map as:
```yaml
value_map:
  true: "Open"
  false: "Closed"
```

Matching order: exact equality → `int(value)` → `str(int(value))`. Unmapped values pass through unchanged.

---

## Validation

Protects `total_increasing` energy counters from spikes (inverter startup noise, communication glitches).

```yaml
validation:
  min: 0.0        # reject if value < min
  max: 30.0       # reject if value > max (same unit as decoded output)
  max_delta: 5.0  # reject if |value − last_valid| > max_delta per poll
```

On failure: entity keeps its last valid state. First poll after HA restart: entity is unavailable until a valid reading arrives. All rejections logged at DEBUG.

---

## Polling hints

Some devices require reading a fixed block regardless of how many entities are defined. Without hints, the coordinator auto-batches contiguous addresses.

```yaml
polling:
  input:
    start_address: 0
    count: 80
  holding:
    start_address: 0
    count: 10
  coil:
    start_address: 0
    count: 8
  discrete_input:
    start_address: 0
    count: 8
```

Use polling hints when:
- Device responds incorrectly to reads of arbitrary length
- You want to force a single request for a sparse set of registers

---

## Parameters (for configurable devices)

Some devices need user-supplied values (e.g. rated power for validation). Declare them so the config UI prompts the user:

```yaml
parameters:
  rated_power_kw:
    name: "Rated Power"
    description: "Inverter nameplate power in kW"
    unit: "kW"
    min: 1.0
    max: 50.0
    default: 5.0
```

Reference in validation: `max: "{rated_power_kw}"` — the coordinator substitutes the user-supplied value.

---

## Complete examples

### FLOAT32 energy meter entity

```yaml
- id: import_active_energy
  name: "Import Active Energy"
  register_type: input
  address: 72
  entity_type: sensor
  data_type: FLOAT32
  byte_order: BIG
  unit: "kWh"
  device_class: energy
  state_class: total_increasing
  precision: 1
```

### UINT16 with value_map (config register)

```yaml
- id: baud_rate
  name: "Baud Rate"
  register_type: holding
  address: 28
  entity_type: sensor
  data_type: FLOAT32
  byte_order: BIG
  readonly: true
  entity_category: diagnostic
  value_map:
    0: "2400 bps"
    1: "4800 bps"
    2: "9600 bps"
```

### Relay coil (switch)

```yaml
- id: relay_1
  name: "Relay 1"
  register_type: coil
  address: 0
  entity_type: switch
```

### Scaled holding register (number)

```yaml
- id: output_ratio
  name: "Output Ratio"
  register_type: holding
  address: 4
  entity_type: number
  data_type: UINT16
  scale: 0.01
  unit: "%"
  precision: 1
```

### PV inverter power with validation

```yaml
- id: ac_power
  name: "AC Power"
  register_type: input
  address: 186
  entity_type: sensor
  data_type: INT16
  byte_order: BIG
  scale: 0.01
  unit: "kW"
  device_class: power
  state_class: measurement
  precision: 2
  validation:
    min: 0.0
    max: "{rated_power_kw}"
    max_delta: 2.0
```

---

## AI prompt usage

To generate a YAML definition for a new device, provide an AI assistant with:
1. The full content of this file
2. The device's Modbus register map (from manufacturer documentation)
3. The following instruction:

> Write a Modbus Manager YAML definition for [device name]. Use FLOAT32 big-endian for all registers unless the documentation specifies otherwise. Group entities into sections with comments: primary measurements first (no entity_category), then diagnostic. Use the device class / unit table from the format guide. For energy counters use total_increasing. For config registers add readonly: true and entity_category: diagnostic.
