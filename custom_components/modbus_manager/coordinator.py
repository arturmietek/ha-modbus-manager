"""DataUpdateCoordinator for Modbus Manager."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta, datetime, timezone
from typing import Any

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_BUS_TYPE_RTU,
    CONF_HOST,
    CONF_TCP_PORT,
    CONF_PORT,
    CONF_BAUDRATE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_BYTESIZE,
    CONF_TIMEOUT,
    CONF_SLAVE_ID,
    CONF_DEVICE_ID,
    CONF_SCAN_INTERVAL,
    CONF_DEFINITION,
    CONF_DEVICE_PARAMS,
    CONF_DEVICE_ENABLED,
    CONF_POLL_PRIORITY,
    DEFAULT_SCAN_INTERVAL,
    OFFLINE_BACKOFF_CAP_S,
    REGISTER_COIL,
    REGISTER_DISCRETE_INPUT,
    REGISTER_HOLDING,
    REGISTER_INPUT,
    DATA_TYPE_UINT16,
    DATA_TYPE_STRING,
    BYTE_ORDER_BIG,
    DOMAIN,
)
from .modbus_device import decode_value, apply_value_map, apply_bitmask, REGISTER_COUNT

_LOGGER = logging.getLogger(__name__)

# Sentinel returned by _validate_and_track when the value should be withheld entirely
# (validation failed with no prior good value). Distinct from None which is a valid
# mapped value (e.g. STATUS_UNKNOWN mapped to null in YAML).
_WITHHELD = object()


def _eval_param_expr(value: Any, params: dict[str, float]) -> Any:
    """Evaluate a {expression} string against device params; return value unchanged if not an expression."""
    if not isinstance(value, str) or "{" not in value:
        return value
    expr = value.strip("{}").strip()
    try:
        return eval(expr, {"__builtins__": {}}, params)  # noqa: S307
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Failed to evaluate parameter expression %r with params %s", value, params)
        return value


def _apply_device_params(device: dict) -> dict:
    """Bake device_params into entity validation fields by resolving {expr} placeholders."""
    params: dict[str, float] = device.get(CONF_DEVICE_PARAMS, {})
    if not params:
        return device

    definition = device.get(CONF_DEFINITION, {})
    resolved_entities = []
    for entity in definition.get("entities", []):
        validation = entity.get("validation")
        if not validation:
            resolved_entities.append(entity)
            continue
        entity = dict(entity)
        entity["validation"] = {k: _eval_param_expr(v, params) for k, v in validation.items()}
        resolved_entities.append(entity)

    device = dict(device)
    device[CONF_DEFINITION] = {**definition, "entities": resolved_entities}
    return device



class ModbusManagerCoordinator(DataUpdateCoordinator):
    """Polls a single Modbus bus and all devices attached to it."""

    def __init__(self, hass: HomeAssistant, bus_config: dict, devices: list[dict]) -> None:
        self._bus_config = bus_config
        prepared = [_apply_device_params(d) for d in devices]
        self._devices = sorted(prepared, key=_device_priority)
        self._client: AsyncModbusSerialClient | AsyncModbusTcpClient | None = None
        # Consecutive failure count per device_id; warning only after OFFLINE_WARN_THRESHOLD
        self._failure_counts: dict[str, int] = {}
        self._offline_warn_threshold: int = bus_config.get("offline_warn_threshold", 3)
        # Per-register-group error counts: device_id → start_addr → consecutive_failures
        self._reg_error_counts: dict[str, dict[int, int]] = {}
        # Last known-good value per device_id → entity_id; returned on validation failure
        self._last_valid: dict[str, dict[str, Any]] = {}

        self._bus_scan_interval: float = float(bus_config.get("scan_interval", DEFAULT_SCAN_INTERVAL))

        # Per-device poll interval: explicit > YAML definition hint > bus default
        self._device_intervals: dict[str, float] = {
            d[CONF_DEVICE_ID]: float(
                d.get(CONF_SCAN_INTERVAL)
                or d.get(CONF_DEFINITION, {}).get("scan_interval")
                or self._bus_scan_interval
            )
            for d in self._devices
        }
        # Monotonic timestamps of the last completed poll per device
        self._last_polled: dict[str, float] = {}

        # Coordinator fires at the fastest device interval so no device is starved
        effective_interval = min(self._device_intervals.values(), default=self._bus_scan_interval)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=effective_interval),
        )

    @property
    def devices(self) -> list[dict]:
        return self._devices

    def _build_client(self) -> AsyncModbusSerialClient | AsyncModbusTcpClient:
        bus_type = self._bus_config.get("bus_type")
        timeout = self._bus_config.get(CONF_TIMEOUT, 3)

        if bus_type == CONF_BUS_TYPE_RTU:
            return AsyncModbusSerialClient(
                port=self._bus_config[CONF_PORT],
                baudrate=self._bus_config[CONF_BAUDRATE],
                parity=self._bus_config[CONF_PARITY],
                stopbits=self._bus_config[CONF_STOPBITS],
                bytesize=self._bus_config[CONF_BYTESIZE],
                timeout=timeout,
            )
        else:
            return AsyncModbusTcpClient(
                host=self._bus_config[CONF_HOST],
                port=self._bus_config[CONF_TCP_PORT],
                timeout=timeout,
            )

    async def async_connect(self) -> bool:
        """Open connection to the Modbus bus."""
        self._client = self._build_client()
        connected = await self._client.connect()
        if not connected:
            _LOGGER.error("Could not connect to Modbus bus: %s", self._bus_config)
        return connected

    async def async_disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
            # Yield to event loop so transport callbacks finish before HA tears down
            await asyncio.sleep(0)

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch data from all devices on this bus."""
        if not self._client or not self._client.connected:
            try:
                connected = await self.async_connect()
            except Exception as exc:
                raise UpdateFailed(f"Cannot connect to Modbus bus: {exc}") from exc
            if not connected:
                raise UpdateFailed("Cannot connect to Modbus bus")

        result: dict[str, dict[str, Any]] = {}
        now = time.monotonic()

        for device in self._devices:
            device_id: str = device[CONF_DEVICE_ID]
            slave_id: int = device[CONF_SLAVE_ID]
            definition: dict = device[CONF_DEFINITION]

            if not device.get(CONF_DEVICE_ENABLED, True):
                result[device_id] = self.data.get(device_id, {}) if self.data else {}
                continue

            device_interval = _effective_interval(
                base=self._device_intervals.get(device_id, self._bus_scan_interval),
                fail_count=self._failure_counts.get(device_id, 0),
                threshold=self._offline_warn_threshold,
            )
            last = self._last_polled.get(device_id, 0.0)
            if self.data is not None and (now - last) < device_interval:
                result[device_id] = self.data.get(device_id, {})
                continue
            self._last_polled[device_id] = now

            try:
                t0 = time.monotonic()
                device_data = await self._poll_device(slave_id, definition, device_id=device_id)
                poll_ms = int((time.monotonic() - t0) * 1000)
                if device_id in self._failure_counts:
                    _LOGGER.info("Device %s (slave %d) back online", device_id, slave_id)
                    del self._failure_counts[device_id]
                device_data["_poll_last_success"] = datetime.now(timezone.utc)
                device_data["_poll_error_count"] = 0
                device_data["_poll_duration_ms"] = poll_ms
                result[device_id] = device_data
            except ModbusException as err:
                fail_count = self._failure_counts.get(device_id, 0) + 1
                self._failure_counts[device_id] = fail_count
                if fail_count == self._offline_warn_threshold:
                    _LOGGER.warning(
                        "Device %s (slave %d) offline for %d consecutive polls: %s",
                        device_id, slave_id, fail_count, err,
                    )
                elif fail_count > self._offline_warn_threshold:
                    _LOGGER.debug("Device %s (slave %d) still offline (attempt %d)", device_id, slave_id, fail_count)
                else:
                    _LOGGER.debug("Device %s (slave %d) missed poll %d/%d: %s", device_id, slave_id, fail_count, self._offline_warn_threshold, err)
                prev = self.data.get(device_id, {}) if self.data else {}
                result[device_id] = {
                    "_poll_last_success": prev.get("_poll_last_success"),
                    "_poll_error_count": fail_count,
                    "_poll_duration_ms": prev.get("_poll_duration_ms"),
                }
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Unexpected error for device %s: %s", device_id, err)
                result[device_id] = {}

        return result

    async def _poll_device(self, slave_id: int, definition: dict, device_id: str = "") -> dict[str, Any]:
        """Read all registers for one device and return entity_id → value mapping."""
        data: dict[str, Any] = {}
        entities: list[dict] = definition.get("entities", [])
        polling_hints: dict = definition.get("polling", {})
        inter_delay: float = polling_hints.get("inter_read_delay_ms", 0) / 1000
        max_read_count: int = polling_hints.get("max_read_count", 125)

        read_types_done = 0  # counts FC types already sent, to insert delay before each subsequent one

        async def _maybe_delay() -> None:
            nonlocal read_types_done
            if read_types_done > 0 and inter_delay > 0:
                await asyncio.sleep(inter_delay)
            read_types_done += 1

        # ── Coils ─────────────────────────────────────────────────────────────
        coil_entities = [e for e in entities if e.get("register_type") == REGISTER_COIL]
        if coil_entities:
            await _maybe_delay()
            hint = polling_hints.get("coils", {})
            start = hint.get("start_address", 0)
            count = hint.get("count") or (max(e["address"] for e in coil_entities) - start + 1)
            rr = await self._client.read_coils(start, count=count, device_id=slave_id)
            if not rr.isError():
                for entity in coil_entities:
                    idx = entity["address"] - start
                    if 0 <= idx < len(rr.bits):
                        data[entity["id"]] = apply_value_map(rr.bits[idx], entity.get("value_map") or {})

        # ── Discrete inputs ───────────────────────────────────────────────────
        di_entities = [e for e in entities if e.get("register_type") == REGISTER_DISCRETE_INPUT]
        if di_entities:
            await _maybe_delay()
            hint = polling_hints.get("discrete_inputs", {})
            start = hint.get("start_address", 0)
            count = hint.get("count") or (max(e["address"] for e in di_entities) - start + 1)
            rr = await self._client.read_discrete_inputs(start, count=count, device_id=slave_id)
            if not rr.isError():
                for entity in di_entities:
                    idx = entity["address"] - start
                    if 0 <= idx < len(rr.bits):
                        data[entity["id"]] = apply_value_map(rr.bits[idx], entity.get("value_map") or {})

        # ── Holding registers ─────────────────────────────────────────────────
        holding_entities = [e for e in entities if e.get("register_type") == REGISTER_HOLDING]
        if holding_entities:
            await _maybe_delay()
            data.update(await self._read_register_entities(holding_entities, slave_id, is_holding=True, device_id=device_id, inter_delay=inter_delay, max_read_count=max_read_count))

        # ── Input registers ───────────────────────────────────────────────────
        input_entities = [e for e in entities if e.get("register_type") == REGISTER_INPUT]
        if input_entities:
            await _maybe_delay()
            data.update(await self._read_register_entities(input_entities, slave_id, is_holding=False, device_id=device_id, inter_delay=inter_delay, max_read_count=max_read_count))

        return data

    async def _read_register_entities(
        self, entities: list[dict], slave_id: int, is_holding: bool, device_id: str = "", inter_delay: float = 0.0, max_read_count: int = 125
    ) -> dict[str, Any]:
        """Batch-read a list of register entities, grouping contiguous blocks."""
        data: dict[str, Any] = {}
        groups = _build_groups(entities, max_read_count)

        for group_idx, (start, count, group_entities) in enumerate(groups):
            if group_idx > 0 and inter_delay > 0:
                await asyncio.sleep(inter_delay)

            if not self._client:
                raise ModbusException("Client disconnected during poll")
            if is_holding:
                rr = await self._client.read_holding_registers(start, count=count, device_id=slave_id)
            else:
                rr = await self._client.read_input_registers(start, count=count, device_id=slave_id)

            if rr.isError():
                dev_reg_counts = self._reg_error_counts.setdefault(device_id, {})
                fail_count = dev_reg_counts.get(start, 0) + 1
                dev_reg_counts[start] = fail_count
                if fail_count == 1:
                    _LOGGER.warning(
                        "Register read error for device %s at addr %d count %d — "
                        "further failures at this address will be suppressed (DEBUG)",
                        device_id, start, count,
                    )
                else:
                    _LOGGER.debug(
                        "Device %s register addr %d still unavailable (attempt %d)",
                        device_id, start, fail_count,
                    )
                continue

            # Successful read — clear any prior error count for this group
            dev_reg_counts = self._reg_error_counts.get(device_id, {})
            if start in dev_reg_counts:
                _LOGGER.info(
                    "Device %s register addr %d count %d recovered",
                    device_id, start, count,
                )
                del dev_reg_counts[start]

            for entity in group_entities:
                addr = entity["address"]
                reg_count = _reg_count(entity)
                idx = addr - start
                raw_regs = rr.registers[idx : idx + reg_count]

                if len(raw_regs) < reg_count:
                    continue

                data_type = entity.get("data_type", DATA_TYPE_UINT16)
                byte_order = entity.get("byte_order", BYTE_ORDER_BIG)
                scale = entity.get("scale", 1.0)
                offset = entity.get("offset", 0.0)

                try:
                    raw = decode_value(raw_regs, data_type, byte_order, scale, offset)
                    if entity.get("bitmask"):
                        value = apply_bitmask(int(raw), entity["bitmask"])
                    else:
                        value = apply_value_map(raw, entity.get("value_map") or {})
                    published = self._validate_and_track(value, entity, device_id)
                    if published is not _WITHHELD:
                        data[entity["id"]] = published
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Decode error for entity %s: %s", entity["id"], err)

        return data

    def _validate_and_track(self, value: Any, entity: dict, device_id: str) -> Any:
        """Validate value against entity rules; return value or last-known-good on failure.

        Returns _WITHHELD when validation fails and there is no prior good value.
        None is a valid publishable value (value_map entry mapped to null in YAML).
        """
        validation: dict | None = entity.get("validation")
        entity_id: str = entity["id"]

        if not validation or not isinstance(value, (int, float)):
            self._last_valid.setdefault(device_id, {})[entity_id] = value
            return value

        min_val = validation.get("min")
        max_val = validation.get("max")
        max_delta = validation.get("max_delta")
        failure_reason: str | None = None

        if min_val is not None and value < min_val:
            failure_reason = f"value {value} below min {min_val}"
        elif max_val is not None and value > max_val:
            failure_reason = f"value {value} above max {max_val}"
        elif max_delta is not None:
            prev = self._last_valid.get(device_id, {}).get(entity_id)
            if prev is not None and isinstance(prev, (int, float)) and abs(value - prev) > max_delta:
                failure_reason = f"delta {abs(value - prev):.4g} exceeds max_delta {max_delta}"

        if failure_reason:
            device_cache = self._last_valid.get(device_id, {})
            if entity_id in device_cache:
                fallback = device_cache[entity_id]
                _LOGGER.debug("Validation failed for %s.%s: %s — publishing last valid: %s", device_id, entity_id, failure_reason, fallback)
                return fallback
            _LOGGER.debug("Validation failed for %s.%s: %s — no prior value, withholding", device_id, entity_id, failure_reason)
            return _WITHHELD

        self._last_valid.setdefault(device_id, {})[entity_id] = value
        return value

    async def async_write_coil(self, slave_id: int, address: int, value: bool) -> bool:
        """Write a single coil value."""
        if not self._client or not self._client.connected:
            if not await self.async_connect():
                return False
        rr = await self._client.write_coil(address, value, device_id=slave_id)
        return not rr.isError()

    async def async_write_register(self, slave_id: int, address: int, value: int) -> bool:
        """Write a single holding register."""
        if not self._client or not self._client.connected:
            if not await self.async_connect():
                return False
        rr = await self._client.write_register(address, value, device_id=slave_id)
        return not rr.isError()

    async def async_force_refresh_device(self, device_id: str) -> None:
        """Bypass the poll interval for one device and trigger an immediate refresh.

        Resets the per-device poll timestamp so _async_update_data will re-poll
        this device on the next coordinator cycle, then requests that cycle now.
        Call this after any write that should be reflected in HA state immediately.
        """
        self._last_polled[device_id] = 0.0
        await self.async_request_refresh()


def _effective_interval(base: float, fail_count: int, threshold: int) -> float:
    """Return poll interval with exponential backoff when a device is offline.

    Doubles on every step past threshold, capped at OFFLINE_BACKOFF_CAP_S.
    """
    if fail_count >= threshold:
        steps = fail_count - threshold
        return min(base * (2 ** steps), OFFLINE_BACKOFF_CAP_S)
    return base


def _build_groups(entities: list[dict], max_read_count: int = 125) -> list[tuple[int, int, list[dict]]]:
    """Sort entities by address and merge contiguous blocks into minimal read ranges.

    Returns list of (start_addr, count, entities_in_group).
    Entities are contiguous when the next address is within 1 register of the
    current group end (no gap or immediately adjacent). Groups are split when
    their total register count would exceed max_read_count.
    """
    sorted_entities = sorted(entities, key=lambda e: e["address"])
    groups: list[tuple[int, int, list[dict]]] = []
    current_start: int | None = None
    current_end: int | None = None
    current_group: list[dict] = []

    for entity in sorted_entities:
        addr = entity["address"]
        rc = _reg_count(entity)
        entity_end = addr + rc - 1

        if current_start is None:
            current_start = addr
            current_end = entity_end
            current_group = [entity]
        elif addr <= current_end + 1 and (entity_end - current_start + 1) <= max_read_count:
            current_end = max(current_end, entity_end)
            current_group.append(entity)
        else:
            groups.append((current_start, current_end - current_start + 1, current_group))
            current_start = addr
            current_end = entity_end
            current_group = [entity]

    if current_start is not None:
        groups.append((current_start, current_end - current_start + 1, current_group))

    return groups


def _device_priority(device: dict) -> int:
    """Return poll priority for a device (lower = polled first).

    Checks per-device config key first, then falls back to the YAML definition's
    poll_priority field. Defaults to 0 (highest priority).
    """
    explicit = device.get(CONF_POLL_PRIORITY)
    if explicit is not None:
        return int(explicit)
    return int(device.get(CONF_DEFINITION, {}).get("poll_priority", 0))


def _reg_count(entity: dict) -> int:
    """Return number of 16-bit registers consumed by this entity."""
    data_type = entity.get("data_type", DATA_TYPE_UINT16)
    if data_type == DATA_TYPE_STRING:
        return entity.get("register_count", 8)
    return REGISTER_COUNT.get(data_type, 1)


