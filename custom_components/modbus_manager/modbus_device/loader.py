"""Load a device definition YAML file into a DeviceDefinition."""
from __future__ import annotations
from pathlib import Path

import yaml

from .model import DeviceDefinition, EntityDef, PollingGroup


def load_device_definition(path: str | Path) -> DeviceDefinition:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    polling: dict[str, PollingGroup] = {}
    for reg_type, hint in (raw.get("polling") or {}).items():
        polling[reg_type] = PollingGroup(
            start_address=hint["start_address"],
            count=hint["count"],
        )

    entities: list[EntityDef] = []
    for e in raw.get("entities", []):
        vm = e.get("value_map") or {}
        entities.append(EntityDef(
            id=e["id"],
            name=e["name"],
            register_type=e["register_type"],
            address=e["address"],
            entity_type=e.get("entity_type", "sensor"),
            data_type=e.get("data_type", "UINT16"),
            byte_order=e.get("byte_order", "BIG"),
            scale=float(e.get("scale", 1.0)),
            offset=float(e.get("offset", 0.0)),
            unit=e.get("unit") or "",
            precision=e.get("precision"),
            readonly=bool(e.get("readonly", False)),
            value_map=dict(vm),
        ))

    desc = raw.get("description") or ""
    if isinstance(desc, str):
        desc = desc.strip()

    return DeviceDefinition(
        name=raw.get("name", "Unknown Device"),
        manufacturer=raw.get("manufacturer", ""),
        model=raw.get("model", ""),
        version=raw.get("version", ""),
        description=desc,
        scan_interval=int(raw.get("scan_interval", 10)),
        entities=entities,
        polling=polling,
    )
