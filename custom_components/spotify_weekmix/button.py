"""Buttons: rebuild now, never this artist/track again."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MEDIA_PLAYERS
from .entity import MixEntity


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    mgr = entry.runtime_data
    async_add_entities([RebuildButton(mgr), BlockArtistButton(mgr), BlockTrackButton(mgr)])


class RebuildButton(MixEntity, ButtonEntity):
    _attr_translation_key = "rebuild_today"
    _attr_icon = "mdi:playlist-refresh"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "rebuild_today")

    async def async_press(self) -> None:
        await self.mgr.async_rebuild([self.mgr.today_name()])


class _PlayerButton(MixEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        return bool(self.mgr.ha.get(CONF_MEDIA_PLAYERS))


class BlockArtistButton(_PlayerButton):
    _attr_translation_key = "block_current_artist"
    _attr_icon = "mdi:account-cancel"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "block_current_artist")

    async def async_press(self) -> None:
        await self.mgr.async_block_artist(None, None)


class BlockTrackButton(_PlayerButton):
    _attr_translation_key = "block_current_track"
    _attr_icon = "mdi:music-note-off"

    def __init__(self, mgr) -> None:
        super().__init__(mgr, "block_current_track")

    async def async_press(self) -> None:
        await self.mgr.async_block_track(None, None)
