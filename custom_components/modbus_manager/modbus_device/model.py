from __future__ import annotations
from dataclasses import dataclass, field

# Number of 16-bit registers occupied by each data type
REGISTER_COUNT: dict[str, int] = {
    "UINT16": 1, "INT16": 1,
    "UINT32": 2, "INT32": 2, "FLOAT32": 2,
    "INT64": 4,
}


@dataclass
class PollingGroup:
    start_address: int
    count: int


@dataclass
class EntityDef:
    id: str
    name: str
    register_type: str   # "holding" | "input" | "coil" | "discrete_input"
    address: int
    entity_type: str = "sensor"
    data_type: str = "UINT16"
    byte_order: str = "BIG"
    scale: float = 1.0
    offset: float = 0.0
    unit: str = ""
    precision: int | None = None
    readonly: bool = False
    value_map: dict = field(default_factory=dict)

    @property
    def register_count(self) -> int:
        return REGISTER_COUNT.get(self.data_type, 1)


@dataclass
class DeviceDefinition:
    name: str
    manufacturer: str = ""
    model: str = ""
    version: str = ""
    description: str = ""
    scan_interval: int = 10
    entities: list[EntityDef] = field(default_factory=list)
    polling: dict[str, PollingGroup] = field(default_factory=dict)

    def entity_by_id(self, entity_id: str) -> EntityDef | None:
        for e in self.entities:
            if e.id == entity_id:
                return e
        return None
