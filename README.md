# ha-modbus-manager

[![License: MIT](https://img.shields.io/github/license/arturmietek/ha-modbus-manager)](LICENSE)
[![Release](https://img.shields.io/github/v/release/arturmietek/ha-modbus-manager)](https://github.com/arturmietek/ha-modbus-manager/releases)
[![Downloads](https://img.shields.io/github/downloads/arturmietek/ha-modbus-manager/total)](https://github.com/arturmietek/ha-modbus-manager/releases)
[![Tests](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/tests.yaml/badge.svg)](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/tests.yaml)
[![CodeQL](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/codeql.yml/badge.svg)](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/codeql.yml)
[![HACS Validation](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/hacs.yaml/badge.svg)](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/hacs.yaml)
[![hassfest](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/hassfest.yaml/badge.svg)](https://github.com/arturmietek/ha-modbus-manager/actions/workflows/hassfest.yaml)

Native Home Assistant integration for Modbus RTU (RS-485) and TCP buses. Define any Modbus device in a YAML file — sensors, switches, covers, and binary sensors appear automatically in HA with correct device classes, units, and energy dashboard support.

## Installation

**Via HACS** (recommended): add this repository as a custom integration repository, install *Modbus Manager*, restart HA.

**Manual:**
```bash
scp -r custom_components/modbus_manager root@homeassistant.local:/config/custom_components/
```
Restart Home Assistant after copying.

## Setup

1. **Settings → Devices & Services → Add Integration → Modbus Manager**
2. Choose bus type: **RTU** (USB/serial adapter) or **TCP** (Ethernet/WiFi gateway)
3. Configure bus parameters (port/baud or host/port)
4. In the integration options, add one or more devices (Modbus slaves):
   - Give the device a name and slave ID
   - Pick a built-in definition, select from your user library, or paste a custom YAML

Definitions in `/config/modbus_manager/*.yaml` are picked up automatically on restart — edit them freely without re-adding devices.

## Built-in devices

| File | Device | Notes |
|------|--------|-------|
| `eastron_sdm120m.yaml` | Eastron SDM120-M | Single-phase energy meter |
| `eastron_sdm630_modbus.yaml` | Eastron SDM630 | Three-phase energy meter, verified |
| `sofarsolar_ktl_x.yaml` | SofarSolar KTL-X | Three-phase PV inverter, dual MPPT |
| `sofarsolar_tl_g3.yaml` | SofarSolar TL-G3 | Single-phase PV inverter |
| `shenzen_lc_relay_input_board.yaml` | Shenzen LC 8×relay + 8×DI | Relay + digital input board |
| `modbus_gate_controller.yaml` | Gate/barrier controller | Cover entity |
| `eletechsup_r4cva02.yaml` | Eletechsup R4CVA02 | 2-channel voltage (0–10 V) |
| `eletechsup_r4ivb02.yaml` | Eletechsup R4IVB02 | 2-channel current (4–20 mA) |
| `eletechsup_n4aia04.yaml` | Eletechsup N4AIA04 | 4-channel analog input |

## Adding a new device

The typical workflow: explore registers with pymodbus REPL → write YAML → verify with CLI monitor → add to HA.

See **[docs/NEW_DEVICE.md](docs/NEW_DEVICE.md)** for a step-by-step guide.

## YAML definition format

See **[docs/YAML_FORMAT.md](docs/YAML_FORMAT.md)** for the complete field reference, valid device class / state class combinations, and worked examples. The format guide is written to be usable as an AI prompt — paste it together with a device's Modbus register map to generate a working YAML.

## CLI monitor

A terminal UI for real-time register inspection and editing — useful for commissioning without a running HA instance. Reads the same YAML device definitions.

```bash
# Install
pipx install git+https://github.com/arturmietek/ha-modbus-manager.git

# RTU
modbus-monitor --port /dev/ttyUSB0 --slave 1 device.yaml

# TCP
modbus-monitor --host 192.168.1.100 --slave 1 device.yaml
```

Displays both raw register values (hex) and decoded/scaled values side by side.

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate editable registers |
| `Space` | Toggle coil |
| `Enter` | Edit holding register |
| `q` | Exit |

## Repository structure

```
ha-modbus-manager/
├── custom_components/
│   └── modbus_manager/          # HA custom component
│       ├── device_definitions/  # Built-in YAML device files
│       └── modbus_device/       # Shared decoder library
├── docs/
│   ├── YAML_FORMAT.md           # YAML schema reference + AI prompt
│   └── NEW_DEVICE.md            # New device implementation workflow
├── modbus_monitor.py            # CLI monitor
└── pyproject.toml
```

## Developer reference

See [custom_components/modbus_manager/README.md](custom_components/modbus_manager/README.md) for architecture, coordinator internals, and known limitations.
