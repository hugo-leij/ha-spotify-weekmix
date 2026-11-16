"""Common base for the entities."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATED
from .manager import MixManager


class MixEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, mgr: MixManager, key: str) -> None:
        self.mgr = mgr
        self._attr_unique_id = f"{mgr.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mgr.entry.entry_id)},
            name=f"Spotify weekmix ({mgr.entry.title})",
            manufacturer="Spotify weekmix",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(
            self.hass, SIGNAL_UPDATED.format(self.mgr.entry.entry_id), self._updated))

    @callback
    def _updated(self) -> None:
        self.async_write_ha_state()
