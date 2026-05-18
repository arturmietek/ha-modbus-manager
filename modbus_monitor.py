#!/usr/bin/env python3
"""
Modbus register monitor — RTU (serial) and TCP (Ethernet/WiFi).

Usage:
    modbus-monitor path/to/device.yaml
    modbus-monitor --port /dev/ttyUSB0 --slave 1 path/to/device.yaml
    modbus-monitor --host 192.168.1.100 --slave 1 path/to/device.yaml
    modbus-monitor --host 192.168.1.100 --tcp-port 502 --slave 1 path/to/device.yaml
"""

import argparse
import curses
import logging
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

# Suppress pymodbus connection-error logs so they don't corrupt the curses display
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)

try:
    from pymodbus.client import ModbusSerialClient, ModbusTcpClient
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


# ── colors ────────────────────────────────────────────────────────────────────

_COLORS_INITIALIZED = False
_LABEL_W = 36
_RAW_W   = 20
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


# ── transport / connection selection ─────────────────────────────────────────

def _select_transport(stdscr) -> str | None:
    """Return 'rtu', 'tcp', or None (quit)."""
    _init_colors()
    curses.curs_set(0)
    options = [
        ("rtu", "RTU  — serial port / USB adapter"),
        ("tcp", "TCP  — Ethernet / WiFi"),
    ]
    selected = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        sep = "─" * min(w - 1, 60)
        try:
            stdscr.addstr(0, 0, "Select transport", curses.A_BOLD | curses.color_pair(2))
            stdscr.addstr(1, 0, sep)
        except curses.error:
            pass
        for i, (_, label) in enumerate(options):
            marker = "►" if i == selected else " "
            attr = curses.color_pair(4) | curses.A_BOLD if i == selected else curses.A_NORMAL
            try:
                stdscr.addstr(i + 3, 0, f"  {marker} {label}"[:w - 1], attr)
            except curses.error:
                pass
        try:
            stdscr.addstr(h - 1, 0, "↑↓ navigate · Enter select · q quit"[:w - 1])
        except curses.error:
            pass
        stdscr.refresh()
        key = stdscr.getch()
        if key == curses.KEY_UP:
            selected = max(0, selected - 1)
        elif key == curses.KEY_DOWN:
            selected = min(len(options) - 1, selected + 1)
        elif key in (curses.KEY_ENTER, ord('\n'), ord('\r')):
            return options[selected][0]
        elif key in (ord('q'), ord('Q'), 27):
            return None


def _list_ports():
    return list(serial.tools.list_ports.comports())


def _select_port(stdscr) -> str | None:
    ports = _list_ports()
    _init_colors()
    curses.curs_set(0)

    selected = 0
    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        try:
            stdscr.addstr(0, 0, "Select serial port", curses.A_BOLD | curses.color_pair(2))
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
                attr = curses.color_pair(4) | curses.A_BOLD if i == selected else curses.A_NORMAL
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


def _enter_tcp_config(stdscr, default_host: str = "", default_port: int = 502) -> tuple[str, int] | None:
    """Interactive TCP host/port entry. Returns (host, port) or None."""
    _init_colors()
    curses.curs_set(0)
    host   = default_host
    port   = default_port
    status = ""

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        sep = "─" * min(w - 1, 60)
        row = 0
        try:
            stdscr.addstr(row, 0, "TCP connection", curses.A_BOLD | curses.color_pair(2))
        except curses.error:
            pass
        row += 1
        try:
            stdscr.addstr(row, 0, sep)
        except curses.error:
            pass
        row += 2

        host_display = host if host else "(not set)"
        try:
            stdscr.addstr(row, 0, f"  Host:  {host_display}"[:w - 1])
            stdscr.addstr(row, w - 18, "← h to edit"[:w - 1])
        except curses.error:
            pass
        row += 1
        try:
            stdscr.addstr(row, 0, f"  Port:  {port}"[:w - 1])
            stdscr.addstr(row, w - 18, "← p to edit"[:w - 1])
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
            stdscr.addstr(h - 1, 0, "h edit host · p edit port · s start · q quit"[:w - 1])
        except curses.error:
            pass

        stdscr.refresh()
        key = stdscr.getch()

        if key in (ord('q'), ord('Q')):
            return None
        elif key in (ord('s'), ord('S')):
            if not host:
                status = "Host required — press h to enter IP address"
            else:
                return (host, port)
        elif key in (ord('h'), ord('H'), curses.KEY_ENTER, ord('\n'), ord('\r')):
            new_host = _prompt_text(stdscr, h, w, "Host / IP address", current=host)
            if new_host is not None:
                host   = new_host
                status = ""
            else:
                status = "Edit cancelled"
        elif key in (ord('p'), ord('P')):
            new_port = _prompt_int(stdscr, h, w, "TCP port",
                                   current=str(port), min_val=1, max_val=65535)
            if new_port is not None:
                port   = new_port
                status = ""
            else:
                status = "Edit cancelled"


# ── preset config screens ─────────────────────────────────────────────────────

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


_ERR = ([], "ERR")


def _fmt_raw(raw: list) -> str:
    """Format raw register list as hex string, e.g. '0x449A 0x0000'."""
    if not raw:
        return ""
    return " ".join(f"0x{r:04X}" for r in raw)


def read_from_definition(client, slave_id: int, definition) -> dict:
    """YAML mode: read all entities, return {entity_id: (raw_regs, decoded_value)}."""
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
            try:
                r    = read_fn(hint.start_address, count=hint.count, device_id=slave_id)
                pool = list(getattr(r, attr)) if not r.isError() else None
            except ModbusException:
                pool = None

            for entity in entities:
                if pool is None:
                    results[entity.id] = _ERR
                    continue
                idx = entity.address - hint.start_address
                n   = REGISTER_COUNT.get(entity.data_type, 1)
                raw = pool[idx:idx + n]
                if len(raw) < n:
                    results[entity.id] = _ERR
                    continue
                try:
                    val = decode_value(raw, entity.data_type, entity.byte_order,
                                       entity.scale, entity.offset)
                    results[entity.id] = (raw, apply_value_map(val, entity.value_map))
                except Exception:
                    results[entity.id] = _ERR
        else:
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
                        results[entity.id] = _ERR
                        continue
                    try:
                        raw_reg = [pool[i]]
                        val = decode_value(raw_reg, entity.data_type, entity.byte_order,
                                           entity.scale, entity.offset)
                        results[entity.id] = (raw_reg, apply_value_map(val, entity.value_map))
                    except Exception:
                        results[entity.id] = _ERR

            for entity in multi:
                n = entity.register_count
                try:
                    r   = read_fn(entity.address, count=n, device_id=slave_id)
                    raw = list(getattr(r, attr)) if not r.isError() else None
                except ModbusException:
                    raw = None
                if raw is None:
                    results[entity.id] = _ERR
                    continue
                try:
                    raw_regs = raw[:n]
                    val = decode_value(raw_regs, entity.data_type, entity.byte_order,
                                       entity.scale, entity.offset)
                    results[entity.id] = (raw_regs, apply_value_map(val, entity.value_map))
                except Exception:
                    results[entity.id] = _ERR

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
    def __init__(self, client, interval: float, definition, slave_ids: list[int]):
        super().__init__(daemon=True)
        self.client     = client
        self.interval   = interval
        self.definition = definition
        self.slave_ids  = slave_ids
        self._stop      = threading.Event()
        self._lock      = threading.Lock()
        self._data: dict = {}

    def stop(self):
        self._stop.set()

    def get_data(self) -> dict:
        with self._lock:
            return dict(self._data)

    def run(self):
        while not self._stop.is_set():
            for slave_id in self.slave_ids:
                if self._stop.is_set():
                    return
                t0      = time.monotonic()
                data    = read_from_definition(self.client, slave_id, self.definition)
                elapsed = int((time.monotonic() - t0) * 1000)
                with self._lock:
                    self._data[slave_id] = (data, elapsed)
            self._stop.wait(self.interval)


# ── inline editors ────────────────────────────────────────────────────────────

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


def _prompt_text(stdscr, h: int, w: int, label: str, current: str = "") -> str | None:
    buf = current
    curses.curs_set(1)
    curses.cbreak()
    try:
        while True:
            prompt = f" {label} → {buf}▌  (Enter confirm · Esc cancel)"
            try:
                stdscr.addstr(h - 1, 0, " " * (w - 1))
                stdscr.addstr(h - 1, 0, prompt[:w - 1], curses.A_REVERSE)
            except curses.error:
                pass
            stdscr.refresh()
            key = stdscr.getch()
            if key in (ord('\n'), ord('\r'), curses.KEY_ENTER):
                return buf if buf else None
            elif key == 27:
                return None
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                buf = buf[:-1]
            elif 32 <= key <= 126:
                buf += chr(key)
    finally:
        curses.curs_set(0)
        curses.halfdelay(2)


# ── rendering ─────────────────────────────────────────────────────────────────

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

        entry = all_data.get(row.slave_id, ({}, 0))[0].get(row.key, ([], "?"))
        raw_regs, value = entry if isinstance(entry, tuple) else ([], entry)

        raw_display = _fmt_raw(raw_regs) if raw_regs else ""

        if _YAML_SUPPORT and row.unit:
            val_display = format_value(value, row.precision, row.unit)
        else:
            val_display = str(value)

        col_label = f"  {row.label:<{_LABEL_W - 2}}"
        is_sel    = (row is selected)

        try:
            if is_sel:
                hint = "Enter edit" if row.nav == "edit" else "Space toggle"
                line = f"{col_label}{raw_display:<{_RAW_W}}{val_display:<{_VAL_W}}  ← {hint}"
                stdscr.addstr(scr_row, 0, line[:w - 1], curses.color_pair(4) | curses.A_BOLD)
            else:
                stdscr.addstr(scr_row, 0, col_label[:w - 1])
                rc = len(col_label)
                if rc < w - 1:
                    stdscr.addstr(scr_row, rc,
                                  raw_display[:_RAW_W].ljust(_RAW_W)[:w - rc - 1],
                                  curses.color_pair(5) | curses.A_DIM)
                vc = rc + _RAW_W
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

def _build_client(conn_info: dict):
    """Create and return the appropriate Modbus client (not yet connected)."""
    if conn_info["type"] == "tcp":
        return ModbusTcpClient(
            host=conn_info["host"],
            port=conn_info["port"],
            timeout=3,
        )
    return ModbusSerialClient(
        port=conn_info["port"],
        baudrate=conn_info["baud"],
        bytesize=8, parity="N", stopbits=1, timeout=0.3,
    )


def _conn_label(conn_info: dict) -> str:
    if conn_info["type"] == "tcp":
        return f"{conn_info['host']}:{conn_info['port']}"
    return conn_info["port"]


def _run_monitor(stdscr, interval: float, conn_info: dict,
                 rows: list[_Row], poller_kwargs: dict, title: str):
    curses.curs_set(0)
    curses.halfdelay(2)

    conn_str = _conn_label(conn_info)
    client   = _build_client(conn_info)

    if not client.connect():
        curses.nocbreak()
        stdscr.clear()
        try:
            stdscr.addstr(0, 0, f"Failed to connect to {conn_str}. Press any key.")
        except curses.error:
            pass
        stdscr.refresh()
        stdscr.getch()
        return

    nav_items    = [r for r in rows if r.nav is not None]
    cursor       = 0
    status_msg   = ""
    status_until = 0.0

    poller = _Poller(client, interval, **poller_kwargs)
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
                    entry    = snapshot.get(row.slave_id, ({}, 0))[0].get(row.key)
                    value    = entry[1] if isinstance(entry, tuple) else entry

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
                    stdscr.addstr(0, 0, f"Connecting to {conn_str}…")
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
    parser = argparse.ArgumentParser(description="Modbus register monitor — RTU and TCP")
    parser.add_argument("preset_pos", nargs="?", metavar="PRESET",
                        help="Device definition YAML file")
    parser.add_argument("--preset",    default=None,
                        help="Same as positional PRESET (flag form)")
    # RTU options
    parser.add_argument("--port",      default=None,
                        help="Serial port for RTU, e.g. /dev/ttyUSB0 or COM3; omit for interactive picker")
    parser.add_argument("--baud",      type=int, default=9600,
                        help="Baud rate for RTU (default: 9600)")
    # TCP options
    parser.add_argument("--host",      default=None,
                        help="Host / IP address for TCP mode, e.g. 192.168.1.100")
    parser.add_argument("--tcp-port",  type=int, default=502,
                        help="TCP port (default: 502)")
    # Common
    parser.add_argument("--slave",     type=int, default=None, metavar="ID",
                        help="Slave / unit ID 1–247 (YAML mode); skips the config screen")
    parser.add_argument("--interval",  type=float, default=0.5,
                        help="Refresh interval in seconds (default: 0.5)")
    args = parser.parse_args()

    if args.port and args.host:
        parser.error("--port and --host are mutually exclusive; pick one transport")

    # Resolve preset: positional arg takes priority over --preset flag
    preset_str = args.preset_pos or args.preset
    if not preset_str:
        parser.error("PRESET argument is required")
    preset_path = Path(preset_str)
    if not preset_path.exists():
        print(f"Device definition file not found: {preset_path}")
        sys.exit(1)
    if preset_path.suffix not in (".yaml", ".yml"):
        print(f"Expected a YAML file (.yaml / .yml), got: {preset_path.name}")
        sys.exit(1)

    # Resolve connection
    if args.host:
        conn_info = {"type": "tcp", "host": args.host, "port": args.tcp_port}
    elif args.port:
        conn_info = {"type": "rtu", "port": args.port, "baud": args.baud}
    else:
        # Interactive transport selection
        transport = curses.wrapper(_select_transport)
        if transport is None:
            sys.exit(0)
        if transport == "tcp":
            tcp_cfg = curses.wrapper(_enter_tcp_config)
            if tcp_cfg is None:
                sys.exit(0)
            conn_info = {"type": "tcp", "host": tcp_cfg[0], "port": tcp_cfg[1]}
        else:
            port = curses.wrapper(_select_port)
            if port is None:
                sys.exit(0)
            conn_info = {"type": "rtu", "port": port, "baud": args.baud}

    # Load device definition
    if not _YAML_SUPPORT:
        print("modbus_device library not found — reinstall: pipx install . --force")
        sys.exit(1)
    definition      = load_device_definition(preset_path)
    transport_label = _conn_label(conn_info)

    if args.slave is not None:
        slave_ids = [args.slave]
    else:
        slave_ids = curses.wrapper(_configure_preset_yaml, str(preset_path), definition)
        if slave_ids is None:
            sys.exit(0)

    rows          = _rows_from_yaml(definition, slave_ids)
    poller_kwargs = {"definition": definition, "slave_ids": slave_ids}
    title = (f"Modbus Monitor  {definition.name}  "
             f"{transport_label}  {time.strftime('%H:%M:%S')}")

    curses.wrapper(_run_monitor, args.interval, conn_info, rows, poller_kwargs, title)


if __name__ == "__main__":
    main()
