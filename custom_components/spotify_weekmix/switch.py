"""Switch: daily automatic refresh on/off."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_AUTO_REFRESH
from .entity import MixEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    async_add_entities([AutoRefreshSwitch(entry.runtime_data)])


class AutoRefreshSwitch(MixEntity, SwitchEntity):
    _attr_translation_key = "auto_refresh"
    _attr_icon = "mdi:calendar-sync"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "auto_refresh")

    @property
    def is_on(self) -> bool:
        return bool(self.mgr.ha.get(CONF_AUTO_REFRESH))

    async def _set(self, on: bool) -> None:
        await self.mgr.async_update_settings(lambda s: s["ha"].__setitem__(CONF_AUTO_REFRESH, on))
        self.mgr.reschedule()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
