"""Koppeling tussen Home Assistant en de motor (engine.py)."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
from typing import Any

from spotipy import Spotify

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import engine
from .const import (
    CONF_MEDIA_PLAYERS,
    CONF_SHUFFLE_OFF,
    CONF_SKIP_ON_BLOCK,
    COVER_SCOPE,
    DOMAIN,
    HA_DEFAULTS,
    SIGNAL_UPDATED,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

DEFAULTS_PATH = os.path.join(os.path.dirname(__file__), "defaults.json")


def load_defaults() -> dict:
    with open(DEFAULTS_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def merge_defaults(settings: dict, defaults: dict) -> dict:
    """Vult ontbrekende sleutels aan (na een update met nieuwe instellingen),
    zonder iets te overschrijven wat de gebruiker al heeft ingesteld."""
    out = copy.deepcopy(settings)
    for k, v in defaults.items():
        if k not in out:
            out[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(out[k], dict) and k != "days":
            for k2, v2 in v.items():
                out[k].setdefault(k2, copy.deepcopy(v2))
    for day in engine.WEEKDAYS:
        out.setdefault("days", {}).setdefault(day, copy.deepcopy(defaults["days"][day]))
        for k2, v2 in defaults["days"][day].items():
            out["days"][day].setdefault(k2, copy.deepcopy(v2) if k2 != "target" else "")
    for k, v in HA_DEFAULTS.items():
        out.setdefault("ha", {}).setdefault(k, copy.deepcopy(v))
    return out


class MixManager:
    """Eén per config entry: instellingen, geheugen, runs en blokkeren."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry,
                 session: config_entry_oauth2_flow.OAuth2Session) -> None:
        self.hass = hass
        self.entry = entry
        self.session = session
        self.store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.settings: dict = {}
        self.history: dict[str, str] = {}
        self.results: dict[str, dict] = {}       # dag -> laatste DayResult (zonder uris)
        self.last_error: str | None = None
        self.running: str | None = None
        self._lock = asyncio.Lock()
        self._reauth_asked = False

    # ---------- opslag ----------
    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        defaults = await self.hass.async_add_executor_job(load_defaults)
        self.settings = merge_defaults(data.get("settings") or defaults, defaults)
        self.history = data.get("history") or {}
        self.results = data.get("results") or {}
        if not data:
            await self.async_save()

    async def async_save(self) -> None:
        await self.store.async_save({
            "settings": self.settings, "history": self.history, "results": self.results,
        })

    @property
    def ha(self) -> dict:
        return self.settings["ha"]

    def notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATED.format(self.entry.entry_id))

    # ---------- Spotify ----------
    async def _client(self) -> Spotify:
        try:
            await self.session.async_ensure_token_valid()
        except Exception as err:  # noqa: BLE001 - token vernieuwen faalt -> opnieuw inloggen
            raise HomeAssistantError(f"Spotify login expired: {err}") from err
        return Spotify(auth=self.session.token["access_token"], requests_timeout=20, retries=5)

    def _has_cover_scope(self) -> bool:
        """Zit het recht voor covers in de login? Zonder 'scope'-veld in het token
        weten we het niet: dan gewoon proberen (een 401/403 vraagt alsnog om
        opnieuw inloggen)."""
        scope = self.session.token.get("scope")
        return scope is None or COVER_SCOPE in str(scope).split()

    def _engine(self, sp: Spotify, settings: dict, history: dict) -> engine.MixEngine:
        return engine.MixEngine(sp, settings, history, log=lambda m: _LOGGER.info(m),
                                allow_covers=self._has_cover_scope())

    def _maybe_reauth_for_covers(self, eng: engine.MixEngine | None = None) -> None:
        """Covers aan maar de login (van vóór 0.2.0) mist het recht: vraag één
        keer om opnieuw in te loggen. Verversen gaat gewoon door zonder cover."""
        if not self.settings["general"].get("covers", True):
            return
        if self._has_cover_scope() and not (eng and eng.cover_needs_reauth):
            return
        if not self._reauth_asked:
            self._reauth_asked = True
            _LOGGER.warning("Covers need an extra Spotify permission; please re-authenticate")
            self.entry.async_start_reauth(self.hass)

    # ---------- verversen ----------
    async def async_rebuild(self, days: list[str], dry_run: bool = False) -> dict[str, dict]:
        """Bouwt de opgegeven dagen opnieuw op. Eén run tegelijk."""
        if self._lock.locked():
            raise HomeAssistantError("A rebuild is already running.")
        async with self._lock:
            out: dict[str, dict] = {}
            today = dt_util.now().date()
            for day in days:
                self.running = day
                self.notify()
                sp = await self._client()
                settings = copy.deepcopy(self.settings)
                history = dict(self.history)
                eng = self._engine(sp, settings, history)
                try:
                    res = await self.hass.async_add_executor_job(
                        lambda e=eng, d=day: e.build_day(d, today=today, dry_run=dry_run))
                except Exception as err:  # noqa: BLE001
                    self.last_error = f"{day}: {err}"
                    _LOGGER.exception("Rebuild failed for %s", day)
                    out[day] = {"day": day, "error": str(err)}
                    continue
                res = dict(res)
                res.pop("uris", None)
                res["finished"] = dt_util.now().isoformat()
                out[day] = res
                if not dry_run:
                    self.history = history
                    if eng.settings_changed:          # nieuwe doelplaylist en/of cover gezet
                        for d in engine.WEEKDAYS:
                            self.settings["days"][d]["target"] = settings["days"][d]["target"]
                        self.settings["cover_done"] = settings.get("cover_done", {})
                    self._maybe_reauth_for_covers(eng)
                    self.results[day] = res
                    self.last_error = None
                    await self.async_save()
            self.running = None
            self.notify()
            if not dry_run and self.ha.get(CONF_SHUFFLE_OFF):
                await self.async_shuffle_off()
            return out

    async def async_shuffle_off(self) -> None:
        for entity_id in self.ha.get(CONF_MEDIA_PLAYERS) or []:
            try:
                await self.hass.services.async_call(
                    "media_player", "shuffle_set",
                    {"entity_id": entity_id, "shuffle": False}, blocking=True)
            except Exception as err:  # noqa: BLE001 - speler uit / ondersteunt het niet
                _LOGGER.warning("Turning shuffle off failed on %s: %s", entity_id, err)

    # ---------- blokkeren ----------
    def _player(self, entity_id: str | None):
        entity_id = entity_id or next(iter(self.ha.get(CONF_MEDIA_PLAYERS) or []), None)
        if not entity_id:
            raise HomeAssistantError("No player given and no player configured.")
        state = self.hass.states.get(entity_id)
        if state is None:
            raise HomeAssistantError(f"Player {entity_id} does not exist.")
        return entity_id, state

    async def _skip(self, entity_id: str | None) -> None:
        if entity_id and self.ha.get(CONF_SKIP_ON_BLOCK):
            try:
                await self.hass.services.async_call(
                    "media_player", "media_next_track", {"entity_id": entity_id}, blocking=True)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Skipping to next track on %s failed: %s", entity_id, err)

    async def async_block_artist(self, artist: str | None, entity_id: str | None) -> dict[str, Any]:
        player = None
        if not artist:
            player, state = self._player(entity_id)
            artist = state.attributes.get("media_artist")
            if not artist:
                raise HomeAssistantError(f"{player} is not playing a track with an artist.")
        # Sonos/Spotify geven bij een collab soms 'A, B' of 'A & B': neem de eerste.
        names = [a.strip() for a in str(artist).replace(" & ", ",").split(",") if a.strip()]
        name = names[0] if names else str(artist).strip()
        lst = self.settings.setdefault("block_artists", [])
        if name.lower() not in {a.lower() for a in lst}:
            lst.append(name)
        await self.async_save()
        removed = await self._remove(artist=name)
        await self._skip(player)
        self.notify()
        _LOGGER.info("Artist blocked: %s (%s tracks removed from the playlists)", name, removed)
        return {"artist": name, "removed": removed}

    async def async_block_track(self, track: str | None, entity_id: str | None) -> dict[str, Any]:
        player = None
        key = None
        tid = engine.track_id(track or "")
        if not tid:
            player, state = self._player(entity_id)
            tid = engine.track_id(str(state.attributes.get("media_content_id") or ""))
            artist = state.attributes.get("media_artist")
            title = state.attributes.get("media_title")
            if artist and title:
                key = engine.song_key(str(artist).split(",")[0].split(" & ")[0], str(title))
            if not tid and not key:
                raise HomeAssistantError(f"{player} is not playing a recognisable track.")
        lst = self.settings.setdefault("block_tracks", [])
        entries = []
        if tid:
            entries.append(f"spotify:track:{tid}")
        if key:
            entries.append(key)                       # vangt ook andere releases van dezelfde song
        for e in entries:
            if e not in lst:
                lst.append(e)
        # Ook uit de seeds halen (die gaan anders langs elk filter).
        for cfg in self.settings["days"].values():
            cfg["seeds"] = [s for s in cfg.get("seeds", []) if engine.track_id(s) != tid] if tid else cfg.get("seeds", [])
        await self.async_save()
        removed = await self._remove(track_uri=f"spotify:track:{tid}" if tid else None)
        await self._skip(player)
        self.notify()
        return {"blocked": entries, "removed": removed}

    async def async_unblock_artist(self, artist: str) -> dict[str, Any]:
        lst = self.settings.get("block_artists", [])
        before = len(lst)
        self.settings["block_artists"] = [a for a in lst if a.lower() != artist.lower().strip()]
        await self.async_save()
        self.notify()
        return {"artist": artist, "removed_from_blocklist": before - len(self.settings["block_artists"])}

    async def _remove(self, **kwargs) -> int:
        sp = await self._client()
        eng = self._engine(sp, self.settings, {})
        return await self.hass.async_add_executor_job(lambda: eng.remove_from_lists(**kwargs))

    # ---------- instellingen wijzigen ----------
    async def async_update_settings(self, mutate) -> None:
        mutate(self.settings)
        await self.async_save()
        self.notify()

    def today_name(self) -> str:
        return engine.WEEKDAYS[dt_util.now().weekday()]
