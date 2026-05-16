# ha-modbus-manager

Modbus RTU toolkit for Home Assistant. Consists of three parts that share a common device model:

- **Custom component** — native Home Assistant integration supporting sensors, switches, numbers, binary sensors, and covers. Device behavior is defined in per-device YAML files with register maps, scaling, value mapping, and polling hints.
- **CLI monitor** — terminal UI for real-time register inspection and editing. Reads the same YAML device definitions. Useful for device commissioning and debugging without a running Home Assistant instance.
- **Device library** (`modbus_device`) — shared Python package with the device definition model, YAML loader, and register decoder. Used by both the component and the monitor.

## Repository structure

```
ha-modbus-manager/
├── custom_components/
│   └── modbus_manager/          # Home Assistant custom component (installed by HACS)
│       ├── device_definitions/  # Per-device YAML files
│       └── modbus_device/       # Shared device library (bundled)
├── modbus_monitor.py            # CLI monitor entry point
├── pyproject.toml               # pip/pipx install → modbus-monitor CLI
└── hacs.json
```

## Installation

### Home Assistant component (via HACS)

1. Add this repository as a custom HACS repository (type: Integration)
2. Install **Modbus Manager** from HACS
3. Restart Home Assistant
4. Add integration via **Settings → Devices & Services → Add Integration → Modbus Manager**

### CLI monitor

```bash
pipx install git+https://github.com/arturmietek/ha-modbus-manager.git
```

Or from a local clone:

```bash
git clone https://github.com/arturmietek/ha-modbus-manager.git
cd ha-modbus-manager
pipx install .
```

Run:

```bash
modbus-monitor custom_components/modbus_manager/device_definitions/modbus_gate_controller.yaml
modbus-monitor --port /dev/ttyUSB0 --slave 1 custom_components/modbus_manager/device_definitions/modbus_gate_controller.yaml
```

## CLI monitor usage

```bash
modbus-monitor device.yaml                                       # transport picker → slave config
modbus-monitor --port /dev/ttyUSB0 --slave 1 device.yaml        # RTU, no prompts
modbus-monitor --host 192.168.1.100 --slave 1 device.yaml       # TCP, no prompts
modbus-monitor --host 192.168.1.100 --tcp-port 502 --slave 1 device.yaml
```

| Option | Default | Description |
|--------|---------|-------------|
| `PRESET` | *(required)* | Device definition YAML file (positional or `--preset`) |
| `--port` | *(picker)* | RTU serial port, e.g. `/dev/ttyUSB0` or `COM3` |
| `--baud` | `9600` | RTU baud rate |
| `--host` | *(picker)* | TCP host / IP address, e.g. `192.168.1.100` |
| `--tcp-port` | `502` | TCP port |
| `--slave` | *(config screen)* | Slave / unit ID 1–247; skips the interactive config screen |
| `--interval` | `0.5` | Refresh interval in seconds |

When neither `--port` nor `--host` is given, an interactive picker lets you choose the transport (RTU or TCP) and then the serial port or IP address. When `--slave` is omitted, a config screen lets you set it interactively.

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate between editable registers |
| `Space` | Toggle coil / switch |
| `Enter` | Edit holding register value |
| `q` / `Ctrl+C` | Exit |

## Device definitions

YAML files in `custom_components/modbus_manager/device_definitions/` describe register maps for supported devices. The format is shared between the HA component and the CLI monitor.

### Supported devices

| File | Device |
|------|--------|
| `shenzen_lc_relay_input_board.yaml` | Shenzen LC 8-channel Relay + Input Board |
| `eastron_sdm120m.yaml` | Eastron SDM120M Single-phase Energy Meter |
| `eastron_sdm630_modbus.yaml` | Eastron SDM630 Three-phase Energy Meter |
| `sofarsolar_ktl_x.yaml` | SofarSolar KTL-X Three-phase Inverter |
| `sofarsolar_tl_g3.yaml` | SofarSolar TL-G3 Single-phase Inverter |
| `eletechsup_r4cva02.yaml` | Eletechsup R4CVA02 Voltage Module |
| `eletechsup_r4ivb02.yaml` | Eletechsup R4IVB02 Current Loop Module |
| `eletechsup_n4aia04.yaml` | Eletechsup N4AIA04 4-channel Analog Input |

## Requirements

- Python 3.10+
- `pymodbus >= 3.0`
- `pyserial >= 3.0`
- `pyyaml >= 6.0`
