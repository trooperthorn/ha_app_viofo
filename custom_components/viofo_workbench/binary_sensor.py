from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from . import DOMAIN
from .entity import WorkbenchEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Connectivity(coordinator,c,"connectivity","Connection") for c in coordinator.data["cameras"]])


class Connectivity(WorkbenchEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        obs = self.camera["observation"]
        if not obs.get("observed_at") or obs.get("stale"):
            return None
        return obs.get("online", False)
