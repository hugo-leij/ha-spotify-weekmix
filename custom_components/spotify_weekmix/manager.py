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
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
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


# Wat er per versie van de standaardinstellingen aan LIJSTEN is toegevoegd. Een
# bestaande installatie krijgt alleen deze nieuwe items erbij (eigen wijzigingen
# blijven staan; iets wat de gebruiker zelf had weggehaald komt niet terug,
# tenzij het in een nieuwere versie opnieuw wordt toegevoegd).
DEFAULT_ADDITIONS: dict[int, dict[str, list[str]]] = {
    2: {"block_genres": ["children's music", "lullaby"]},
}


def merge_defaults(settings: dict, defaults: dict) -> dict:
    """Vult ontbrekende sleutels aan (na een update met nieuwe instellingen),
    zonder iets te overschrijven wat de gebruiker al heeft ingesteld."""
    out = copy.deepcopy(settings)
    have = int(out.get("defaults_version") or 1)       # vóór het aanvullen bepalen!
    for k, v in defaults.items():
        if k == "defaults_version":
            continue
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
    for version in sorted(DEFAULT_ADDITIONS):
        if version > have:
            for key, items in DEFAULT_ADDITIONS[version].items():
                lst = out.setdefault(key, [])
                low = {x.lower() for x in lst}
                lst.extend(x for x in items if x.lower() not in low)
    out["defaults_version"] = max([have, int(defaults.get("defaults_version") or 1), *DEFAULT_ADDITIONS])
    return out


def _first_artist(artist: str) -> str:
    """Sonos/Spotify geven bij een collab 'A, B' of 'A & B': de hoofdartiest."""
    return str(artist).replace(" & ", ",").split(",")[0].strip()


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
        self.recent: list[dict] = []             # laatst gespeelde nummers (nieuwste eerst)
        self._unsub_players = None

    # ---------- opslag ----------
    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        defaults = await self.hass.async_add_executor_job(load_defaults)
        self.settings = merge_defaults(data.get("settings") or defaults, defaults)
        self.history = data.get("history") or {}
        self.results = data.get("results") or {}
        self.recent = data.get("recent") or []
        if not data:
            await self.async_save()

    async def async_save(self) -> None:
        await self.store.async_save({
            "settings": self.settings, "history": self.history, "results": self.results,
            "recent": self.recent,
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
        name = _first_artist(artist) or str(artist).strip()
        lst = self.settings.setdefault("block_artists", [])
        if name.lower() not in {a.lower() for a in lst}:
            lst.append(name)
        await self.async_save()
        self.notify()                                 # sensor/kaart meteen bijgewerkt
        await self._skip(player)
        self._remove_in_background(f"artist {name}", artist=name)
        _LOGGER.info("Artist blocked: %s", name)
        return {"artist": name, "removing_from_playlists": True}

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
                key = engine.song_key(_first_artist(artist), str(title))
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
        self.notify()                                 # sensor/kaart meteen bijgewerkt
        await self._skip(player)
        if tid:
            self._remove_in_background(f"track {tid}", track_uri=f"spotify:track:{tid}")
        return {"blocked": entries, "removing_from_playlists": bool(tid)}

    # ---------- laatst gespeeld (uit de spelers in HA, geen Spotify-API) ----------
    RECENT_MAX = 10

    @callback
    def listen_players(self) -> None:
        """(Opnieuw) luisteren naar de ingestelde spelers. Elk nieuw Spotify-nummer
        dat gaat spelen komt bovenaan de lijst. Kost geen API-verkeer."""
        if self._unsub_players:
            self._unsub_players()
            self._unsub_players = None
        players = list(self.ha.get(CONF_MEDIA_PLAYERS) or [])
        if players:
            self._unsub_players = async_track_state_change_event(
                self.hass, players, self._player_changed)

    @callback
    def stop_listening(self) -> None:
        if self._unsub_players:
            self._unsub_players()
            self._unsub_players = None

    @callback
    def _player_changed(self, event: Event[EventStateChangedData]) -> None:
        new = event.data.get("new_state")
        if new is None or new.state != "playing":
            return
        attrs = new.attributes
        tid = engine.track_id(str(attrs.get("media_content_id") or ""))
        if not tid:                                  # radio, tv, … : geen Spotify-nummer
            return
        if self.recent and self.recent[0].get("track_id") == tid:
            return                                   # zelfde nummer (gegroepeerde speakers, pauze/play)
        self.recent.insert(0, {
            "track_id": tid,
            "uri": f"spotify:track:{tid}",
            "url": f"https://open.spotify.com/track/{tid}",
            "title": attrs.get("media_title"),
            "artist": attrs.get("media_artist"),
            "album": attrs.get("media_album_name"),
            "image": attrs.get("entity_picture"),
            "player": new.entity_id,
            "played_at": new.last_updated.isoformat(),   # last_changed blijft staan bij playing->playing
        })
        del self.recent[self.RECENT_MAX:]
        self.notify()
        self.hass.async_create_task(self.async_save())

    def is_track_blocked(self, item: dict) -> bool:
        bt = self.settings.get("block_tracks", [])
        if item.get("uri") in bt:
            return True
        if item.get("artist") and item.get("title"):
            return engine.song_key(_first_artist(item["artist"]), item["title"]) in bt
        return False

    def is_artist_blocked(self, item: dict) -> bool:
        name = _first_artist(item.get("artist") or "").lower()
        return bool(name) and name in {a.lower() for a in self.settings.get("block_artists", [])}

    async def async_unblock_track(self, track: str) -> dict[str, Any]:
        """Haalt een nummer weer van de blocklist (op link/URI én op artiest|titel).
        Een seed die bij het blokkeren is weggehaald, komt NIET vanzelf terug."""
        tid = engine.track_id(track or "")
        keys = set()
        if tid:
            keys.add(f"spotify:track:{tid}")
            for item in self.recent:
                if item.get("track_id") == tid and item.get("artist") and item.get("title"):
                    keys.add(engine.song_key(_first_artist(item["artist"]), item["title"]))
        elif "|" in (track or ""):
            keys.add(track.strip().lower())
        lst = self.settings.get("block_tracks", [])
        before = len(lst)
        self.settings["block_tracks"] = [x for x in lst if x not in keys]
        await self.async_save()
        self.notify()
        return {"track": track, "removed_from_blocklist": before - len(self.settings["block_tracks"])}

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

    def _remove_in_background(self, what: str, **kwargs) -> None:
        """Uit alle zeven playlists halen kost ~15 s Spotify-API (7 lijsten lezen
        en bijwerken). Daar laten we de knop/service niet op wachten: de blocklist
        is al opgeslagen, dus de volgende verversing slaat het nummer hoe dan ook
        over. Een fout komt in het log en in de Status-sensor."""

        async def _run() -> None:
            try:
                n = await self._remove(**kwargs)
                _LOGGER.info("Removed %s from the playlists (%s tracks)", what, n)
            except Exception as err:  # noqa: BLE001
                self.last_error = f"removing {what}: {err}"
                _LOGGER.warning("Removing %s from the playlists failed: %s", what, err)
                self.notify()

        self.hass.async_create_background_task(_run(), f"spotify_weekmix remove {what}")

    # ---------- instellingen wijzigen ----------
    async def async_update_settings(self, mutate) -> None:
        mutate(self.settings)
        await self.async_save()
        self.notify()

    def today_name(self) -> str:
        return engine.WEEKDAYS[dt_util.now().weekday()]
