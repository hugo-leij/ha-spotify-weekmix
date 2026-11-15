"""Sensors: when and how each day's playlist was last built, plus a status sensor."""

from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import engine
from .const import DAY_KEYS
from .entity import MixEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    mgr = entry.runtime_data
    async_add_entities([DaySensor(mgr, d) for d in engine.WEEKDAYS] + [StatusSensor(mgr)])


class DaySensor(MixEntity, SensorEntity):
    """State = time of the last refresh of that day."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:playlist-music"

    def __init__(self, mgr, day: str) -> None:
        super().__init__(mgr, f"day_{day}")
        self.day = day
        self._attr_translation_key = DAY_KEYS[day]

    @property
    def native_value(self):
        res = self.mgr.results.get(self.day) or {}
        return dt_util.parse_datetime(res["finished"]) if res.get("finished") else None

    @property
    def extra_state_attributes(self):
        res = dict(self.mgr.results.get(self.day) or {})
        res.pop("day", None)
        target = self.mgr.settings["days"][self.day].get("target", "")
        pid = engine.normalize_playlist_id(target)
        res["playlist_url"] = f"https://open.spotify.com/playlist/{pid}" if pid else None
        res["playlist_uri"] = f"spotify:playlist:{pid}" if pid else None
        return res


class StatusSensor(MixEntity, SensorEntity):
    _attr_translation_key = "status"
    _attr_icon = "mdi:spotify"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ok", "running", "error"]

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "status")

    @property
    def native_value(self) -> str:
        if self.mgr.running:
            return "running"
        return "error" if self.mgr.last_error else "ok"

    @property
    def extra_state_attributes(self):
        s = self.mgr.settings
        return {
            "running_day": DAY_KEYS.get(self.mgr.running) if self.mgr.running else None,
            "last_error": self.mgr.last_error,
            "version": engine.ENGINE_VERSION,
            "blocked_artists": len(s.get("block_artists", [])),
            "blocked_tracks": len(s.get("block_tracks", [])),
            "tracks_in_history": len(self.mgr.history),
            "auto_refresh": s["ha"].get("auto_refresh"),
            "refresh_time": s["ha"].get("refresh_time"),
        }
