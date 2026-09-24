from urllib.parse import urlsplit
import aiohttp
import asyncio
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from . import DOMAIN


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input:
            url = user_input["url"].rstrip("/")
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                errors["base"] = "invalid_url"
            else:
                try:
                    async with async_get_clientsession(self.hass).get(url + "/api/status", headers={"Authorization":"Bearer " + user_input["token"]}, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        if r.status in (401,403):
                            errors["base"] = "invalid_auth"
                        else:
                            r.raise_for_status()
                            data = await r.json()
                            if "cameras" not in data:
                                raise ValueError("Not Workbench")
                    if not errors:
                        await self.async_set_unique_id(url)
                        self._abort_if_unique_id_configured()
                        return self.async_create_entry(title="VIOFO Workbench", data={"url":url,"token":user_input["token"]})
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    errors["base"] = "cannot_connect"
        return self.async_show_form(step_id="user", data_schema=vol.Schema({vol.Required("url", default="http://local-viofo-workbench:8100"):str, vol.Required("token"):str}), errors=errors)
