# Adding a New Device

This guide walks through adding a new Modbus device to Modbus Manager — from first contact with the hardware to a working HA integration.

## Prerequisites

- Device connected to RS-485 bus or accessible over TCP
- Serial adapter (for RTU) or Modbus TCP gateway
- Manufacturer's Modbus register map (PDF or datasheet)
- `pymodbus-repl` installed (see below)

---

## Step 1 — Install pymodbus REPL

```bash
pipx install pymodbus-repl --python python3.13
pipx inject pymodbus-repl "pymodbus==3.3.2"
pipx inject pymodbus-repl pyserial
```

> pymodbus-repl 2.0.4 requires exactly pymodbus 3.3.2. Newer versions changed the API.
> On macOS Apple Silicon force Python 3.13 — 3.14+ may have issues.

---

## Step 2 — Connect and discover

### RTU (serial)

Find the port:
```bash
ls /dev/*serial* /dev/cu.usb* /dev/tty.usb* 2>/dev/null
```

Launch REPL:
```bash
pymodbus.console serial \
  --port /dev/cu.usbserial-XXXXXXXX \
  --baudrate 9600 \
  --parity N \
  --stopbits 1 \
  --bytesize 8
```

Common baud rates: 2400, 4800, 9600, 19200. Check the device label or documentation.

### TCP

```bash
pymodbus.console tcp --host 192.168.1.100 --port 502
```

---

## Step 3 — Explore registers in REPL

Use the register map from the documentation. The most common commands:

```
# Read input registers (function code 4) — measurements, read-only
client.read_input_registers address=0 count=10 slave=1

# Read holding registers (function code 3) — config, often read/write
client.read_holding_registers address=0 count=10 slave=1

# Read coils (function code 1) — relay outputs
client.read_coils address=0 count=8 slave=1

# Read discrete inputs (function code 2) — digital inputs
client.read_discrete_inputs address=0 count=8 slave=1

# Write a holding register
client.write_register address=0 value=8 slave=1

# Write a coil
client.write_coil address=0 value=True slave=1
```

**Tips:**
- Start with `count=40` or more to see a broad view before narrowing to specific addresses
- For FLOAT32 devices: values come in pairs of 16-bit registers. Read at least 2 at a time starting from each even address
- Note down: which addresses respond, raw values, expected decoded values (cross-check with a handheld display if available)
- Verify byte order: for a FLOAT32 value you know (e.g. 230 V), check if `struct.unpack(">f", bytes.fromhex(f"{reg0:04x}{reg1:04x}"))` gives the right answer

**Decoding raw FLOAT32 manually (Python):**
```python
import struct
reg0, reg1 = 0x43E6, 0x6666   # example from REPL output
value = struct.unpack(">f", struct.pack(">HH", reg0, reg1))[0]
print(f"{value:.2f}")          # → 460.80
```

---

## Step 4 — Write the YAML definition

Create `custom_components/modbus_manager/device_definitions/<manufacturer>_<model>.yaml`.

Use the register notes from Step 3 and the full format reference:
→ **[docs/YAML_FORMAT.md](YAML_FORMAT.md)**

**Quick checklist:**
- [ ] File name: `manufacturer_model.yaml` (lowercase, underscores)
- [ ] `name`, `manufacturer`, `model`, `version`, `description` filled
- [ ] Each entity has `id`, `name`, `register_type`, `address`, `entity_type`
- [ ] `data_type` and `byte_order` match what you verified in Step 3
- [ ] `device_class` + `state_class` + `unit` match the table in YAML_FORMAT.md
- [ ] Energy counters use `state_class: total_increasing`
- [ ] `power_factor` has no `unit` and value is −1…1 (not percent)
- [ ] Config/identification registers have `entity_category: diagnostic` and `readonly: true`
- [ ] Integer-only values (serial number, version, slave ID) have `precision: 0`

**Using AI to generate the YAML:**

Paste the content of [YAML_FORMAT.md](YAML_FORMAT.md) and the device's register table into an AI assistant with this prompt:

> Write a Modbus Manager YAML definition for [device name]. Use FLOAT32 big-endian for all registers unless the documentation specifies otherwise. Group entities into sections with comments: primary measurements first (no entity_category), then diagnostic. Use the device class / unit table from the format guide. For energy counters use total_increasing. For config registers add readonly: true and entity_category: diagnostic.

Review the output against Step 3 register values before using it.

---

## Step 5 — Verify with CLI monitor

The CLI monitor reads the same YAML format and shows raw hex alongside decoded values — ideal for catching scale, byte order, or address errors before committing to HA.

**Install (if not already):**
```bash
cd ha-modbus-manager
pipx install .
```

**Run:**
```bash
# RTU
modbus-monitor --port /dev/ttyUSB0 --slave 1 \
  custom_components/modbus_manager/device_definitions/mydevice.yaml

# TCP
modbus-monitor --host 192.168.1.100 --slave 1 \
  custom_components/modbus_manager/device_definitions/mydevice.yaml
```

**What to check:**
- Raw hex column matches what you saw in REPL
- Decoded value column shows physically plausible numbers (230 V, 50 Hz, etc.)
- Holding registers with `value_map` show the correct text
- No `ERR` values (address or slave ID wrong if so)
- Writable registers respond to Enter/Space

Iterate on the YAML — changes take effect on next monitor launch (no reinstall needed).

---

## Step 6 — Add to Home Assistant

**Option A — built-in definition (for submission to the repo):**

The file is already in `device_definitions/` from Step 4. After copying the component to HA:
1. Restart HA
2. Go to integration options → Add device
3. The new definition appears in "Built-in device library"

**Option B — user definition (local only):**

Copy the YAML to `/config/modbus_manager/` on your HA instance:
```bash
scp custom_components/modbus_manager/device_definitions/mydevice.yaml \
    root@homeassistant.local:/config/modbus_manager/
```

No restart needed to see it in the UI — it appears under "User library" when adding a device next time.

**Option C — paste in UI:**

In integration options → Add device → "Paste YAML definition": paste the file content directly. It is saved to `/config/modbus_manager/` automatically.

---

## Step 7 — Validate in HA

After adding the device:

1. Check **Settings → Devices & Services → Modbus Manager → your device** — all entities should be present
2. Open **Developer Tools → States** and filter by your device name — values should be non-null and non-unavailable
3. Check **Settings → System → Logs** for any warnings about invalid device class / unit combinations
4. For energy meters: add to **Energy dashboard** and confirm counters increase over time

---

## Naming conventions

Follow these to stay consistent with built-in definitions:

- Entity IDs: `voltage`, `current`, `active_power`, `apparent_power`, `reactive_power`, `power_factor`, `frequency`
- Energy counters: `import_active_energy`, `export_active_energy`, `total_active_energy`
- Reactive energy: `import_reactive_energy`, `export_reactive_energy`, `total_reactive_energy`
- Per-phase prefix: `l1_`, `l2_`, `l3_` (e.g. `l1_voltage`, `l1_active_power`)
- Config registers: `baud_rate`, `meter_id`, `slave_id`, `software_version`, `serial_number`
- Do **not** embed units in IDs (`import_kwh` → `import_active_energy`)

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| All values `ERR` | Wrong slave ID, wrong port, device powered off |
| Wrong numeric value | Wrong byte order — try `LITTLE` instead of `BIG`, or `BIG_SWAP` |
| Value off by ×100 or ÷100 | Wrong `scale` — check manufacturer spec for unit (W vs 0.01W) |
| Entity `unavailable` in HA | `validation` rejects all readings — check `min`/`max` range |
| HA log warns about device class | Wrong `device_class`+`unit` combination — check YAML_FORMAT.md table |
| `power_factor` shown as `12300` | Device sends percent (×100), add `scale: 0.01` and remove `unit` |
