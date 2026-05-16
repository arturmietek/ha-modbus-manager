#!/usr/bin/env python3
"""
Modbus RTU register monitor — supports both legacy JSON presets and
HA-compatible device-definition YAML files.

Usage:
    modbus-monitor                                    # port picker, default preset
    modbus-monitor --port /dev/ttyUSB0
    modbus-monitor --port /dev/ttyUSB0 --preset path/to/device.yaml
    modbus-monitor --port /dev/ttyUSB0 --preset legacy.json
"""

import argparse
import curses
import json
import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Suppress pymodbus connection-error logs so they don't corrupt the curses display
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

try:
    from pymodbus.client import ModbusSerialClient
    from pymodbus.exceptions import ModbusException
except ImportError:
    print("pymodbus not installed. Run: pip install pymodbus")
    sys.exit(1)

try:
    import serial.tools.list_ports
except ImportError:
    print("pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

try:
    from modbus_device import (
        DeviceDefinition, EntityDef, REGISTER_COUNT,
        load_device_definition, decode_value, apply_value_map, format_value,
    )
    _YAML_SUPPORT = True
except ImportError:
    _YAML_SUPPORT = False


# ── display row model ─────────────────────────────────────────────────────────

@dataclass
class _Row:
    key:       str         # key in data dict
    label:     str         # left column
    unit:      str         # appended after value  (YAML only)
    desc:      str         # dim annotation column
    nav:       str | None  # None | "edit" | "toggle"
    reg_addr:  int         # address for writes
    slave_id:  int
    precision: int | None = None


# ── port selection ────────────────────────────────────────────────────────────

def _list_ports():
    return list(serial.tools.list_ports.comports())


def _select_port(stdscr) -> str | None:
    ports = _list_ports()
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)

    selected = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        try:
            stdscr.addstr(0, 0, "Select serial port", curses.A_BOLD)
            stdscr.addstr(1, 0, "↑↓ navigate · Enter select · q quit")
            stdscr.addstr(2, 0, "─" * min(w - 1, 60))
        except curses.error:
            pass

        if not ports:
            try:
                stdscr.addstr(4, 2, "No serial ports found.")
            except curses.error:
                pass
        else:
            for i, port in enumerate(ports):
                row = i + 4
                if row >= h - 1:
                    break
                label = f"  {port.device:<20}  {port.description}"
                attr = curses.color_pair(1) | curses.A_BOLD if i == selected else curses.A_NORMAL
                try:
                    stdscr.addstr(row, 0, label[:w - 1], attr)
                except curses.error:
                    pass

        stdscr.refresh()
        key = stdscr.getch()
        if key == curses.KEY_UP:
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN:
            selected = min(len(ports) - 1, selected + 1)
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            return ports[selected].device if ports else None
        elif key in (ord('q'), ord('Q'), 27):
            return None


# ── preset config screens ─────────────────────────────────────────────────────

def _configure_preset_json(stdscr, preset_path: str, full_preset: dict) -> dict | None:
    """JSON mode: shows device list with editable slave IDs. Returns modified preset or None."""
    _init_colors()
    curses.curs_set(0)

    slaves    = sorted(full_preset.items(), key=lambda x: int(x[0]))
    slave_ids = [k for k, _ in slaves]
    cursor    = 0
    status    = ""

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        sep = "─" * min(w - 1, 60)
        row = 0
        try:
            stdscr.addstr(row, 0, "Preset configuration", curses.A_BOLD | curses.color_pair(2))
        except curses.error:
            pass
        row += 1
        try:
            stdscr.addstr(row, 0, f"  File:  {preset_path}")
        except curses.error:
            pass
        row += 1
        try:
            stdscr.addstr(row, 0, sep)
        except curses.error:
            pass
        row += 2
        try:
            stdscr.addstr(row, 0, "  Slave ID", curses.A_BOLD)
        except curses.error:
            pass
        row += 1

        for i, sid in enumerate(slave_ids):
            is_sel = i == cursor
            attr   = curses.color_pair(4) | curses.A_BOLD if is_sel else curses.A_NORMAL
            dev_desc = slaves[i][1].get("description", "")
            line   = f"  [ {sid} ]  {dev_desc}"
            if is_sel:
                line += "  ← Enter to edit"
            try:
                stdscr.addstr(row, 0, line[:w - 1], attr)
            except curses.error:
                pass
            row += 1

        if status:
            row += 1
            try:
                stdscr.addstr(row, 0, f"  {status}"[:w - 1], curses.color_pair(1))
            except curses.error:
                pass

        try:
            stdscr.addstr(h - 1, 0, "↑↓ select · Enter edit slave ID · s start · q quit"[:w - 1])
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            return None
        elif key in (ord('s'), ord('S')):
            return {slave_ids[i]: regs for i, (_, regs) in enumerate(slaves)}
        elif key == curses.KEY_UP:
            cursor = (cursor - 1) % len(slave_ids); status = ""
        elif key == curses.KEY_DOWN:
            cursor = (cursor + 1) % len(slave_ids); status = ""
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            new_id = _prompt_int(stdscr, h, w, f"Slave ID for entry {cursor + 1}",
                                 current=slave_ids[cursor], min_val=1, max_val=247)
            if new_id is None:
                status = "Edit cancelled"
            elif str(new_id) in [sid for j, sid in enumerate(slave_ids) if j != cursor]:
                status = f"Slave ID {new_id} already used"
            else:
                slave_ids[cursor] = str(new_id); status = ""


def _configure_preset_yaml(stdscr, preset_path: str, definition) -> list[int] | None:
    """YAML mode: shows device info and single editable slave ID. Returns [slave_id] or None."""
    _init_colors()
    curses.curs_set(0)

    slave_id_str = "1"
    status       = ""

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        sep = "─" * min(w - 1, 60)
        row = 0

        try:
            stdscr.addstr(row, 0, "Device configuration", curses.A_BOLD | curses.color_pair(2))
        except curses.error:
            pass
        row += 1

        for label, value in [
            ("File:  ", preset_path),
            ("Device:", definition.name),
            ("Model: ", f"{definition.model}  v{definition.version}" if definition.model else ""),
        ]:
            if value:
                try:
                    stdscr.addstr(row, 0, f"  {label}  {value}"[:w - 1])
                except curses.error:
                    pass
                row += 1

        try:
            stdscr.addstr(row, 0, sep)
        except curses.error:
            pass
        row += 2

        try:
            stdscr.addstr(row, 0, "  Slave ID", curses.A_BOLD)
        except curses.error:
            pass
        row += 1

        line = f"  [ {slave_id_str} ]  ← Enter to edit"
        try:
            stdscr.addstr(row, 0, line[:w - 1], curses.color_pair(4) | curses.A_BOLD)
        except curses.error:
            pass
        row += 1

        if status:
            row += 1
            try:
                stdscr.addstr(row, 0, f"  {status}"[:w - 1], curses.color_pair(1))
            except curses.error:
                pass

        try:
            stdscr.addstr(h - 1, 0, "Enter edit slave ID · s start · q quit"[:w - 1])
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            return None
        elif key in (ord('s'), ord('S')):
            return [int(slave_id_str)]
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            new_id = _prompt_int(stdscr, h, w, "Slave ID",
                                 current=slave_id_str, min_val=1, max_val=247)
            if new_id is not None:
                slave_id_str = str(new_id)
                status = ""
            else:
                status = "Edit cancelled"


# ── register reading ──────────────────────────────────────────────────────────

def _consecutive_groups(entries: list) -> list[list]:
    """Split list of dicts (with 'addr' key) into groups of consecutive addresses."""
    if not entries:
        return []
    ordered = sorted(entries, key=lambda e: e["addr"])
    groups, cur = [], [ordered[0]]
    for e in ordered[1:]:
        if e["addr"] == cur[-1]["addr"] + 1:
            cur.append(e)
        else:
            groups.append(cur)
            cur = [e]
    groups.append(cur)
    return groups


def read_registers(client, slave_id: int, preset: dict) -> dict:
    """JSON mode: read preset registers, return {key_str: raw_value}."""
    results = {}

    def _batch(entries, read_fn, result_attr, prefix):
        for group in _consecutive_groups(entries):
            start = group[0]["addr"]
            try:
                r    = read_fn(start, count=len(group), device_id=slave_id)
                vals = getattr(r, result_attr) if not r.isError() else None
            except ModbusException:
                vals = None
            for i, entry in enumerate(group):
                key          = f"{prefix} {entry['addr']:02d} {entry['label']}"
                results[key] = vals[i] if vals is not None else "ERR"

    _batch(preset.get("holding", []),        client.read_holding_registers, "registers", "HR")
    _batch(preset.get("input", []),           client.read_input_registers,   "registers", "IR")
    _batch(preset.get("coils", []),           client.read_coils,             "bits",      "CO")
    _batch(preset.get("descrete_inputs", []), client.read_discrete_inputs,   "bits",      "DI")
    return results


def _yaml_consecutive_groups(entities: list) -> list[list]:
    """Group EntityDef objects by consecutive .address."""
    if not entities:
        return []
    ordered = sorted(entities, key=lambda e: e.address)
    groups, cur = [], [ordered[0]]
    for e in ordered[1:]:
        if e.address == cur[-1].address + 1:
            cur.append(e)
        else:
            groups.append(cur)
            cur = [e]
    groups.append(cur)
    return groups


def read_from_definition(client, slave_id: int, definition) -> dict:
    """YAML mode: read all entities in definition, return {entity_id: decoded_value}."""
    results = {}

    fn_map = {
        "holding":        (client.read_holding_registers, "registers"),
        "input":          (client.read_input_registers,   "registers"),
        "coil":           (client.read_coils,             "bits"),
        "discrete_input": (client.read_discrete_inputs,   "bits"),
    }

    by_rtype: dict[str, list] = {}
    for e in definition.entities:
        by_rtype.setdefault(e.register_type, []).append(e)

    for reg_type, entities in by_rtype.items():
        read_fn, attr = fn_map.get(reg_type, (None, None))
        if read_fn is None:
            continue

        hint = definition.polling.get(reg_type)
        if hint:
            # One bulk read covering the whole polling window
            try:
                r    = read_fn(hint.start_address, count=hint.count, device_id=slave_id)
                pool = list(getattr(r, attr)) if not r.isError() else None
            except ModbusException:
                pool = None

            for entity in entities:
                if pool is None:
                    results[entity.id] = "ERR"
                    continue
                idx = entity.address - hint.start_address
                n   = REGISTER_COUNT.get(entity.data_type, 1)
                raw = pool[idx:idx + n]
                if len(raw) < n:
                    results[entity.id] = "ERR"
                    continue
                try:
                    val = decode_value(raw, entity.data_type, entity.byte_order,
                                       entity.scale, entity.offset)
                    results[entity.id] = apply_value_map(val, entity.value_map)
                except Exception:
                    results[entity.id] = "ERR"
        else:
            # Auto-group consecutive single-register entities; read multi-reg individually
            single = sorted([e for e in entities if REGISTER_COUNT.get(e.data_type, 1) == 1],
                            key=lambda e: e.address)
            multi  = [e for e in entities if REGISTER_COUNT.get(e.data_type, 1) > 1]

            for group in _yaml_consecutive_groups(single):
                start = group[0].address
                try:
                    r    = read_fn(start, count=len(group), device_id=slave_id)
                    pool = list(getattr(r, attr)) if not r.isError() else None
                except ModbusException:
                    pool = None
                for i, entity in enumerate(group):
                    if pool is None:
                        results[entity.id] = "ERR"
                        continue
                    try:
                        val = decode_value([pool[i]], entity.data_type, entity.byte_order,
                                           entity.scale, entity.offset)
                        results[entity.id] = apply_value_map(val, entity.value_map)
                    except Exception:
                        results[entity.id] = "ERR"

            for entity in multi:
                n = entity.register_count
                try:
                    r   = read_fn(entity.address, count=n, device_id=slave_id)
                    raw = list(getattr(r, attr)) if not r.isError() else None
                except ModbusException:
                    raw = None
                if raw is None:
                    results[entity.id] = "ERR"
                    continue
                try:
                    val = decode_value(raw[:n], entity.data_type, entity.byte_order,
                                       entity.scale, entity.offset)
                    results[entity.id] = apply_value_map(val, entity.value_map)
                except Exception:
                    results[entity.id] = "ERR"

    return results


# ── coil / register writes ────────────────────────────────────────────────────

def toggle_coil(client, slave_id: int, addr: int, current: bool) -> None:
    r = client.write_coil(addr, not current, device_id=slave_id)
    if r.isError():
        raise ModbusException(f"write_coil failed at addr {addr}")


def write_holding(client, slave_id: int, addr: int, value: int) -> None:
    r = client.write_register(addr, value, device_id=slave_id)
    if r.isError():
        raise ModbusException(f"write_register failed at addr {addr}")


# ── row builders ──────────────────────────────────────────────────────────────

def _rows_from_json(full_preset: dict) -> list[_Row]:
    rows = []
    for slave_id_str, preset in sorted(full_preset.items(), key=lambda x: int(x[0])):
        slave_id = int(slave_id_str)
        for entry in preset.get("holding", []):
            a, lbl = entry["addr"], entry["label"]
            rows.append(_Row(key=f"HR {a:02d} {lbl}", label=f"HR {a:02d} {lbl}",
                             unit="", desc=entry.get("description", ""),
                             nav="edit", reg_addr=a, slave_id=slave_id))
        for entry in preset.get("input", []):
            a, lbl = entry["addr"], entry["label"]
            rows.append(_Row(key=f"IR {a:02d} {lbl}", label=f"IR {a:02d} {lbl}",
                             unit="", desc=entry.get("description", ""),
                             nav=None, reg_addr=a, slave_id=slave_id))
        for entry in preset.get("coils", []):
            a, lbl = entry["addr"], entry["label"]
            rows.append(_Row(key=f"CO {a:02d} {lbl}", label=f"CO {a:02d} {lbl}",
                             unit="", desc=entry.get("description", ""),
                             nav="toggle", reg_addr=a, slave_id=slave_id))
        for entry in preset.get("descrete_inputs", []):
            a, lbl = entry["addr"], entry["label"]
            rows.append(_Row(key=f"DI {a:02d} {lbl}", label=f"DI {a:02d} {lbl}",
                             unit="", desc=entry.get("description", ""),
                             nav=None, reg_addr=a, slave_id=slave_id))
    return rows


def _rows_from_yaml(definition, slave_ids: list[int]) -> list[_Row]:
    rows = []
    for slave_id in slave_ids:
        for entity in definition.entities:
            nav = _yaml_nav(entity)
            rows.append(_Row(
                key=entity.id,
                label=entity.name,
                unit=entity.unit or "",
                desc="",
                nav=nav,
                reg_addr=entity.address,
                slave_id=slave_id,
                precision=entity.precision,
            ))
    return rows


def _yaml_nav(entity) -> str | None:
    if entity.readonly:
        return None
    if entity.entity_type == "switch" and entity.register_type == "coil":
        return "toggle"
    if entity.entity_type == "number" and entity.register_type == "holding":
        return "edit"
    return None


# ── polling thread ────────────────────────────────────────────────────────────

class _Poller(threading.Thread):
    def __init__(self, client, interval: float,
                 full_preset=None, definition=None, slave_ids=None):
        super().__init__(daemon=True)
        self.client      = client
        self.interval    = interval
        self.full_preset = full_preset    # JSON mode
        self.definition  = definition     # YAML mode
        self.slave_ids   = slave_ids or []
        self._stop       = threading.Event()
        self._lock       = threading.Lock()
        self._data: dict = {}

    def stop(self):
        self._stop.set()

    def get_data(self) -> dict:
        with self._lock:
            return dict(self._data)

    def run(self):
        while not self._stop.is_set():
            if self.full_preset is not None:
                for slave_id_str, preset in self.full_preset.items():
                    if self._stop.is_set():
                        return
                    slave_id = int(slave_id_str)
                    t0   = time.monotonic()
                    data = read_registers(self.client, slave_id, preset)
                    elapsed = int((time.monotonic() - t0) * 1000)
                    with self._lock:
                        self._data[slave_id] = (data, elapsed)
            else:
                for slave_id in self.slave_ids:
                    if self._stop.is_set():
                        return
                    t0   = time.monotonic()
                    data = read_from_definition(self.client, slave_id, self.definition)
                    elapsed = int((time.monotonic() - t0) * 1000)
                    with self._lock:
                        self._data[slave_id] = (data, elapsed)
            self._stop.wait(self.interval)


# ── inline editor ─────────────────────────────────────────────────────────────

def _prompt_int(stdscr, h: int, w: int, label: str,
                current: str = "", min_val: int | None = None,
                max_val: int | None = None) -> int | None:
    buf = current
    curses.curs_set(1)
    curses.cbreak()
    range_hint = f" [{min_val}–{max_val}]" if min_val is not None and max_val is not None else ""
    try:
        while True:
            prompt = f" {label}{range_hint} → {buf}▌  (Enter confirm · Esc cancel)"
            try:
                stdscr.addstr(h - 1, 0, " " * (w - 1))
                stdscr.addstr(h - 1, 0, prompt[:w - 1], curses.A_REVERSE)
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord('\n'), ord('\r'), curses.KEY_ENTER):
                if not buf:
                    return None
                try:
                    val = int(buf)
                    if min_val is not None and val < min_val:
                        buf = str(min_val); continue
                    if max_val is not None and val > max_val:
                        buf = str(max_val); continue
                    return val
                except ValueError:
                    return None
            elif key == 27:
                return None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
            elif ord('0') <= key <= ord('9') or (key == ord('-') and not buf):
                buf += chr(key)
    finally:
        curses.curs_set(0)
        curses.halfdelay(2)


# ── rendering ─────────────────────────────────────────────────────────────────

_COLORS_INITIALIZED = False
_LABEL_W = 36
_VAL_W   = 12


def _init_colors():
    global _COLORS_INITIALIZED
    if _COLORS_INITIALIZED:
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(5, curses.COLOR_WHITE, -1)
    _COLORS_INITIALIZED = True


def _render(stdscr, title: str, all_data: dict, rows: list[_Row],
            nav_items: list[_Row], cursor: int, status_msg: str):
    _init_colors()
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    sep  = "─" * min(w - 1, 60)
    selected = nav_items[cursor] if nav_items else None
    scr_row  = 0

    try:
        stdscr.addstr(scr_row, 0, title[:w - 1], curses.A_BOLD | curses.color_pair(2))
    except curses.error:
        pass
    scr_row += 1

    current_slave = None
    for row in rows:
        if scr_row >= h - 2:
            break

        # Slave header when slave changes
        if row.slave_id != current_slave:
            current_slave = row.slave_id
            elapsed = all_data.get(row.slave_id, ({}, 0))[1]
            try:
                stdscr.addstr(scr_row, 0, sep)
            except curses.error:
                pass
            scr_row += 1
            try:
                stdscr.addstr(scr_row, 0,
                              f"  Slave {row.slave_id}   poll: {elapsed} ms"[:w - 1],
                              curses.A_BOLD)
            except curses.error:
                pass
            scr_row += 1

        value = all_data.get(row.slave_id, ({}, 0))[0].get(row.key, "?")

        # Format value
        if _YAML_SUPPORT and row.unit:
            val_display = format_value(value, row.precision, row.unit)
        else:
            val_display = str(value)

        col_label = f"  {row.label:<{_LABEL_W - 2}}"
        is_sel    = (row is selected)

        try:
            if is_sel:
                hint = "Enter edit" if row.nav == "edit" else "Space toggle"
                line = f"{col_label}{val_display:<{_VAL_W}}  ← {hint}"
                stdscr.addstr(scr_row, 0, line[:w - 1], curses.color_pair(4) | curses.A_BOLD)
            else:
                stdscr.addstr(scr_row, 0, col_label[:w - 1])
                vc = len(col_label)
                if vc < w - 1:
                    attr = (curses.color_pair(1) | curses.A_BOLD
                            if value == "ERR" else curses.color_pair(3))
                    stdscr.addstr(scr_row, vc, val_display[:w - vc - 1], attr)
                dc = vc + _VAL_W + 2
                if row.desc and dc < w - 1:
                    stdscr.addstr(scr_row, dc, row.desc[:w - dc - 1],
                                  curses.color_pair(5) | curses.A_DIM)
        except curses.error:
            pass
        scr_row += 1

    if scr_row < h - 2:
        try:
            stdscr.addstr(scr_row, 0, sep)
        except curses.error:
            pass
        scr_row += 1

    if status_msg:
        footer = status_msg
    elif nav_items:
        footer = ("↑↓ select · Enter edit · q/Ctrl+C exit"
                  if nav_items[cursor].nav == "edit"
                  else "↑↓ select · Space toggle · q/Ctrl+C exit")
    else:
        footer = "q / Ctrl+C – exit"

    if scr_row < h - 1:
        try:
            stdscr.addstr(scr_row, 0, footer[:w - 1])
        except curses.error:
            pass

    stdscr.refresh()


# ── monitor loop ──────────────────────────────────────────────────────────────

def _run_monitor(stdscr, args, rows, poller_kwargs, title):
    curses.curs_set(0)
    curses.halfdelay(2)

    client = ModbusSerialClient(
        port=args.port, baudrate=args.baud,
        bytesize=8, parity="N", stopbits=1, timeout=0.3,
    )
    if not client.connect():
        curses.nocbreak()
        stdscr.clear()
        try:
            stdscr.addstr(0, 0, f"Failed to connect to {args.port}. Press any key.")
        except curses.error:
            pass
        stdscr.refresh()
        stdscr.getch()
        return

    nav_items    = [r for r in rows if r.nav is not None]
    cursor       = 0
    status_msg   = ""
    status_until = 0.0

    poller = _Poller(client, args.interval, **poller_kwargs)
    poller.start()

    try:
        while True:
            key = stdscr.getch()

            if key in (ord('q'), ord('Q')):
                break

            elif key == curses.KEY_UP and nav_items:
                cursor = (cursor - 1) % len(nav_items)
                status_msg = ""

            elif key == curses.KEY_DOWN and nav_items:
                cursor = (cursor + 1) % len(nav_items)
                status_msg = ""

            elif key in (ord(' '), curses.KEY_ENTER, ord('\n'), ord('\r')):
                if nav_items:
                    row      = nav_items[cursor]
                    snapshot = poller.get_data()
                    value    = snapshot.get(row.slave_id, ({}, 0))[0].get(row.key)

                    if row.nav == "toggle" and key == ord(' ') and value is not None and value != "ERR":
                        try:
                            toggle_coil(client, row.slave_id, row.reg_addr, bool(value))
                            status_msg = f"Toggled {row.label}"
                        except (ModbusException, Exception) as e:
                            status_msg = f"Error: {e}"
                        status_until = time.monotonic() + 2.0

                    elif row.nav == "edit":
                        h, w = stdscr.getmaxyx()
                        current = str(value) if value not in (None, "ERR") else ""
                        new_val = _prompt_int(stdscr, h, w, row.label, current=current)
                        if new_val is not None:
                            try:
                                write_holding(client, row.slave_id, row.reg_addr, new_val)
                                status_msg = f"Written {row.label} = {new_val}"
                            except (ModbusException, Exception) as e:
                                status_msg = f"Error: {e}"
                        else:
                            status_msg = "Edit cancelled"
                        status_until = time.monotonic() + 2.0

            if time.monotonic() > status_until:
                status_msg = ""

            all_data = poller.get_data()
            if all_data:
                _render(stdscr, title, all_data, rows, nav_items, cursor, status_msg)
            else:
                try:
                    stdscr.erase()
                    stdscr.addstr(0, 0, f"Connecting to {args.port}…")
                    stdscr.refresh()
                except curses.error:
                    pass

    except KeyboardInterrupt:
        pass
    finally:
        poller.stop()
        poller.join(timeout=0.5)
        client.close()


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Modbus RTU register monitor")
    parser.add_argument("--port",     default=None,                      help="Serial port; omit for interactive picker")
    parser.add_argument("--baud",     type=int,   default=9600,          help="Baud rate (default: 9600)")
    parser.add_argument("--preset",   default="simulator-preset.json",   help="Register preset (.json) or device definition (.yaml)")
    parser.add_argument("--interval", type=float, default=0.5,           help="Refresh interval in seconds (default: 0.5)")
    args = parser.parse_args()

    if args.port is None:
        args.port = curses.wrapper(_select_port)
        if args.port is None:
            print("No port selected. Exiting.")
            sys.exit(0)

    preset_path = Path(args.preset)
    if not preset_path.exists():
        print(f"Preset file not found: {preset_path}")
        sys.exit(1)

    if preset_path.suffix in (".yaml", ".yml"):
        if not _YAML_SUPPORT:
            print("YAML support requires modbus_device library. Run: pip install -e ../modbus_device")
            sys.exit(1)
        definition = load_device_definition(preset_path)
        slave_ids  = curses.wrapper(_configure_preset_yaml, str(preset_path), definition)
        if slave_ids is None:
            sys.exit(0)
        rows          = _rows_from_yaml(definition, slave_ids)
        poller_kwargs = {"definition": definition, "slave_ids": slave_ids}
        title = (f"Modbus RTU Monitor  {definition.name}  "
                 f"{preset_path.name}  {time.strftime('%H:%M:%S')}")
    else:
        with open(preset_path) as f:
            full_preset = json.load(f)
        full_preset = curses.wrapper(_configure_preset_json, str(preset_path), full_preset)
        if full_preset is None:
            sys.exit(0)
        rows          = _rows_from_json(full_preset)
        poller_kwargs = {"full_preset": full_preset}
        title = f"Modbus RTU Monitor  preset: {preset_path.name}  {time.strftime('%H:%M:%S')}"

    curses.wrapper(_run_monitor, args, rows, poller_kwargs, title)


if __name__ == "__main__":
    main()
