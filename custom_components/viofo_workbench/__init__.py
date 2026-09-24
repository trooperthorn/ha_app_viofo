"""Companion integration for the VIOFO Workbench app."""
from datetime import timedelta
import asyncio
import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
import logging

DOMAIN = "viofo_workbench"
PLATFORMS = ["sensor", "binary_sensor", "button"]


class Coordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, logging.getLogger(__name__), name=DOMAIN,
                         update_interval=timedelta(seconds=30), config_entry=entry)
        self.entry = entry
        self.session = async_get_clientsession(hass)

    async def request(self, path, method="GET"):
        try:
            async with self.session.request(method, self.entry.data["url"].rstrip("/") + "/api/" + path,
                                            headers={"Authorization":"Bearer " + self.entry.data["token"]},
                                            timeout=aiohttp.ClientTimeout(total=90)) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # Deliberately omit exception text: URL could contain host information.
            raise UpdateFailed("Workbench unavailable; verify app address and token") from exc

    async def _async_update_data(self):
        return await self.request("status")


async def async_setup_entry(hass, entry):
    coordinator = Coordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False
