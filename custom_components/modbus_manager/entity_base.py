"""Base class for all Modbus Manager entities."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo, EntityCategory

from .const import DOMAIN
from .coordinator import ModbusManagerCoordinator


class ModbusManagerEntity(CoordinatorEntity[ModbusManagerCoordinator]):
    """Shared base for all entities created by this integration."""

    def __init__(
        self,
        coordinator: ModbusManagerCoordinator,
        device_config: dict,
        entity_def: dict,
    ) -> None:
        super().__init__(coordinator)
        self._device_config = device_config
        self._entity_def = entity_def

        device_id: str = device_config["device_id"]
        device_name: str = device_config["device_name"]
        slave_id: int = device_config["slave_id"]
        definition: dict = device_config["definition"]

        entity_id: str = entity_def["id"]

        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{device_id}_{entity_id}"
        self._attr_name = entity_def.get("name", entity_id)
        self._attr_has_entity_name = True

        manufacturer = definition.get("manufacturer", "Unknown")
        model = definition.get("model", definition.get("name", "Unknown"))

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.config_entry.entry_id}_{device_id}")},
            name=device_name,
            manufacturer=manufacturer,
            model=model,
        )

        entity_category_str = entity_def.get("entity_category")
        if entity_category_str:
            try:
                self._attr_entity_category = EntityCategory(entity_category_str)
            except ValueError:
                pass

        self._slave_id: int = slave_id
        self._entity_id_key: str = entity_id

    @property
    def _entity_value(self) -> Any:
        """Return the current value from coordinator data."""
        device_id = self._device_config["device_id"]
        device_data = self.coordinator.data or {}
        return device_data.get(device_id, {}).get(self._entity_id_key)

    @property
    def available(self) -> bool:
        """Entity is available when coordinator has data for this device."""
        if not self.coordinator.last_update_success:
            return False
        device_id = self._device_config["device_id"]
        device_data = self.coordinator.data or {}
        return self._entity_id_key in device_data.get(device_id, {})
