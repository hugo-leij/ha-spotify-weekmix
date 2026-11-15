"""Spotify Weekmix: elke dag een verse, lange playlist zonder dubbele nummers."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType

from . import engine
from .const import CONF_AUTO_REFRESH, CONF_REFRESH_TIME, DAY_FROM_KEY, DAY_KEYS, DOMAIN
from .manager import MixManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type SpotifyMixConfigEntry = ConfigEntry[MixManager]

ATTR_ENTRY = "config_entry_id"
# Engels naar buiten; de Nederlandse waarden blijven werken (eerste versie).
DAY_ALIASES = {"today": "today", "vandaag": "today", "all": "all", "alle": "all",
               **{k: v for k, v in DAY_FROM_KEY.items()}, **{d: d for d in engine.WEEKDAYS}}


def _manager(hass: HomeAssistant, call: ServiceCall) -> MixManager:
    entries = [e for e in hass.config_entries.async_loaded_entries(DOMAIN)]
    wanted = call.data.get(ATTR_ENTRY)
    if wanted:
        entries = [e for e in entries if e.entry_id == wanted]
    if not entries:
        raise ServiceValidationError("Spotify Weekmix is not set up or not loaded.")
    if len(entries) > 1 and not wanted:
        raise ServiceValidationError("Multiple accounts configured: pass config_entry_id.")
    return entries[0].runtime_data


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Services (één keer, los van de config entries)."""

    async def rebuild(call: ServiceCall) -> ServiceResponse:
        mgr = _manager(hass, call)
        day = DAY_ALIASES[call.data.get("day", "today")]
        days = engine.WEEKDAYS if day == "all" else [mgr.today_name() if day == "today" else day]
        res = await mgr.async_rebuild(days, dry_run=call.data.get("dry_run", False))
        return {"results": {DAY_KEYS[d]: {**r, "day": DAY_KEYS[d]} for d, r in res.items()}}

    async def block_artist(call: ServiceCall) -> ServiceResponse:
        return await _manager(hass, call).async_block_artist(
            call.data.get("artist"), call.data.get("entity_id"))

    async def block_track(call: ServiceCall) -> ServiceResponse:
        return await _manager(hass, call).async_block_track(
            call.data.get("track"), call.data.get("entity_id"))

    async def unblock_artist(call: ServiceCall) -> ServiceResponse:
        return await _manager(hass, call).async_unblock_artist(call.data["artist"])

    base = {vol.Optional(ATTR_ENTRY): cv.string}
    hass.services.async_register(
        DOMAIN, "rebuild", rebuild,
        schema=vol.Schema({**base, vol.Optional("day", default="today"): vol.In(list(DAY_ALIASES)),
                           vol.Optional("dry_run", default=False): cv.boolean}),
        supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(
        DOMAIN, "block_artist", block_artist,
        schema=vol.Schema({**base, vol.Optional("artist"): cv.string,
                           vol.Optional("entity_id"): cv.entity_id}),
        supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(
        DOMAIN, "block_track", block_track,
        schema=vol.Schema({**base, vol.Optional("track"): cv.string,
                           vol.Optional("entity_id"): cv.entity_id}),
        supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(
        DOMAIN, "unblock_artist", unblock_artist,
        schema=vol.Schema({**base, vol.Required("artist"): cv.string}),
        supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SpotifyMixConfigEntry) -> bool:
    try:
        implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry)
    except ValueError as err:
        raise ConfigEntryAuthFailed("Application Credentials are missing") from err
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    try:
        await session.async_ensure_token_valid()
    except Exception as err:  # noqa: BLE001
        raise ConfigEntryAuthFailed(f"Spotify login invalid: {err}") from err

    mgr = MixManager(hass, entry, session)
    await mgr.async_load()
    entry.runtime_data = mgr

    @callback
    def _schedule() -> None:
        if getattr(mgr, "_unsub_time", None):
            mgr._unsub_time()
            mgr._unsub_time = None
        if not mgr.ha.get(CONF_AUTO_REFRESH):
            return
        h, m, s = (int(x) for x in (str(mgr.ha.get(CONF_REFRESH_TIME) or "04:00:00") + ":00:00").split(":")[:3])

        async def _run(now) -> None:
            try:
                await mgr.async_rebuild([engine.WEEKDAYS[now.weekday()]])
            except HomeAssistantError as err:
                _LOGGER.error("Daily refresh failed: %s", err)

        mgr._unsub_time = async_track_time_change(hass, _run, hour=h, minute=m, second=s)
        _LOGGER.info("Spotify Weekmix: daily refresh at %02d:%02d:%02d", h, m, s)

    mgr.reschedule = _schedule
    _schedule()
    entry.async_on_unload(lambda: mgr._unsub_time() if getattr(mgr, "_unsub_time", None) else None)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SpotifyMixConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
