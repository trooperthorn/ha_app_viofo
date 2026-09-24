from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import DeviceInfo
from . import DOMAIN


class WorkbenchEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, camera, key, name):
        super().__init__(coordinator)
        self.cid = camera["id"]
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{self.cid}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, coordinator.entry.entry_id + "_" + self.cid)}, name=camera["name"], manufacturer="VIOFO", model=camera["model"])

    @property
    def camera(self):
        return next(c for c in self.coordinator.data["cameras"] if c["id"] == self.cid)
