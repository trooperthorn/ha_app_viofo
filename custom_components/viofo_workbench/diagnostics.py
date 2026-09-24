async def async_get_config_entry_diagnostics(hass, entry):
    from . import DOMAIN
    co = hass.data[DOMAIN][entry.entry_id]
    data = co.data or {}
    return {"version":data.get("version"), "models":[{"model":c["model"], "configured":c.get("configured")} for c in data.get("cameras",[])], "library":data.get("library"), "connection_ok":co.last_update_success}
