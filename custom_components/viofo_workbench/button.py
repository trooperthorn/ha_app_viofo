from homeassistant.components.button import ButtonEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from . import DOMAIN
from .entity import WorkbenchEntity


async def async_setup_entry(hass, entry, async_add_entities):
    co = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([Action(co,c,key,name) for c in co.data["cameras"] for key,name in [("inspect","Inspect camera"),("sync","Sync recordings")]])


class Action(WorkbenchEntity, ButtonEntity):
    def __init__(self, coordinator, camera, key, name):
        super().__init__(coordinator, camera, key, name)
        self.action = key

    async def async_press(self):
        try:
            await self.coordinator.request(f"cameras/{self.cid}/{self.action}", "POST")
        except UpdateFailed as exc:
            raise HomeAssistantError("Camera action failed; inspect the Workbench diagnostic log") from exc
        await self.coordinator.async_request_refresh()
