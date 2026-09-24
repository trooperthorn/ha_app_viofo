from datetime import datetime, timezone
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass
from . import DOMAIN
from .entity import WorkbenchEntity


async def async_setup_entry(hass, entry, async_add_entities):
    co = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([cls(co,c,key,name) for c in co.data["cameras"] for cls,key,name in
                        [(Firmware,"firmware","Firmware"),(LastDownload,"last_download","Last download"),
                         (Statistic,"recordings","Recordings"),(Statistic,"queued_downloads","Queued downloads"),
                         (Progress,"download_progress","Download progress")]])


class Firmware(WorkbenchEntity, SensorEntity):
    @property
    def native_value(self):
        return self.camera["observation"].get("firmware")


class LastDownload(WorkbenchEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        value = self.camera["observation"].get("last_download")
        return datetime.fromtimestamp(value, timezone.utc) if value else None


class Statistic(WorkbenchEntity, SensorEntity):
    def __init__(self, coordinator, camera, key, name):
        super().__init__(coordinator, camera, key, name)
        self.key = key

    @property
    def native_value(self):
        return self.camera.get("stats", {}).get(self.key)


class Progress(Statistic):
    _attr_native_unit_of_measurement = "%"
