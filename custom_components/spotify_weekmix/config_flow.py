"""Inloggen bij Spotify (OAuth) en alle instellingen via de HA-interface."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from spotipy import Spotify

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers import selector as sel

from . import engine
from .const import (
    CONF_AUTO_REFRESH,
    CONF_MEDIA_PLAYERS,
    CONF_REFRESH_TIME,
    CONF_SHUFFLE_OFF,
    CONF_SKIP_ON_BLOCK,
    DOMAIN,
    SCOPES,
)

_LOGGER = logging.getLogger(__name__)

TEXT_LIST = sel.TextSelector(sel.TextSelectorConfig(multiline=True))


def _lines(value: str | None) -> list[str]:
    return [l.strip() for l in (value or "").splitlines() if l.strip() and not l.strip().startswith("#")]


def _join(values) -> str:
    return "\n".join(str(v) for v in (values or []))


def _num(lo, hi, step=1, unit=None):
    cfg = {"min": lo, "max": hi, "step": step, "mode": sel.NumberSelectorMode.BOX}
    if unit:                                   # None is ongeldig voor HA
        cfg["unit_of_measurement"] = unit
    return sel.NumberSelector(sel.NumberSelectorConfig(**cfg))


class OAuth2FlowHandler(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    DOMAIN = DOMAIN
    VERSION = 1

    @property
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        # show_dialog: zodat je bewust het juiste (huis-)account kiest.
        return {"scope": " ".join(SCOPES), "show_dialog": "true"}

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        sp = Spotify(auth=data["token"]["access_token"], requests_timeout=20)
        try:
            me = await self.hass.async_add_executor_job(sp.me)
        except Exception:  # noqa: BLE001
            return self.async_abort(reason="connection_error")
        await self.async_set_unique_id(me["id"])
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=me.get("display_name") or me["id"], data=data)

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return MixOptionsFlow()


class MixOptionsFlow(OptionsFlow):
    """Menu met: algemeen, per dag, blocklists, spelers & planning."""

    def __init__(self) -> None:
        self._day: str | None = None

    @property
    def mgr(self):
        return self.config_entry.runtime_data

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=["players", "day_select", "blocklists", "general"])

    async def _save(self, mutate) -> ConfigFlowResult:
        await self.mgr.async_update_settings(mutate)
        self.mgr.reschedule()
        return self.async_create_entry(data={})

    # --- spelers & planning ---
    async def async_step_players(self, user_input=None) -> ConfigFlowResult:
        ha = self.mgr.ha
        if user_input is not None:
            def mutate(s):
                s["ha"][CONF_MEDIA_PLAYERS] = user_input.get(CONF_MEDIA_PLAYERS, [])
                for k in (CONF_AUTO_REFRESH, CONF_REFRESH_TIME, CONF_SHUFFLE_OFF, CONF_SKIP_ON_BLOCK):
                    s["ha"][k] = user_input[k]
            return await self._save(mutate)
        schema = vol.Schema({
            vol.Optional(CONF_MEDIA_PLAYERS, default=ha.get(CONF_MEDIA_PLAYERS, [])):
                sel.EntitySelector(sel.EntitySelectorConfig(domain="media_player", multiple=True)),
            vol.Required(CONF_AUTO_REFRESH, default=ha.get(CONF_AUTO_REFRESH, False)): sel.BooleanSelector(),
            vol.Required(CONF_REFRESH_TIME, default=ha.get(CONF_REFRESH_TIME, "04:00:00")): sel.TimeSelector(),
            vol.Required(CONF_SHUFFLE_OFF, default=ha.get(CONF_SHUFFLE_OFF, True)): sel.BooleanSelector(),
            vol.Required(CONF_SKIP_ON_BLOCK, default=ha.get(CONF_SKIP_ON_BLOCK, True)): sel.BooleanSelector(),
        })
        return self.async_show_form(step_id="players", data_schema=schema)

    # --- per dag ---
    async def async_step_day_select(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._day = user_input["day"]
            return await self.async_step_day()
        return self.async_show_form(step_id="day_select", data_schema=vol.Schema({
            vol.Required("day", default=self.mgr.today_name()): sel.SelectSelector(
                sel.SelectSelectorConfig(options=engine.WEEKDAYS, translation_key="day")),
        }))

    async def async_step_day(self, user_input=None) -> ConfigFlowResult:
        day = self._day
        cfg = self.mgr.settings["days"][day]
        if user_input is not None:
            def opt_int(k):
                v = user_input.get(k)
                return int(v) if v not in (None, "") else None

            rebuild_now = bool(user_input.get("rebuild_now"))

            def mutate(s):
                c = s["days"][day]
                c["target"] = (user_input.get("target") or "").strip()
                c["description"] = user_input.get("description", "")
                c["sources"] = [engine.normalize_playlist_id(x) for x in _lines(user_input.get("sources"))]
                c["searches"] = _lines(user_input.get("searches"))
                c["seeds"] = [t for t in (engine.track_id(x) for x in _lines(user_input.get("seeds"))) if t]
                c["min_year"] = opt_int("min_year")
                c["max_rap"] = opt_int("max_rap")
                c["seed_weeks"] = opt_int("seed_weeks")
            result = await self._save(mutate)
            if rebuild_now:
                # Op de achtergrond: duurt ~1 minuut, het venster sluit meteen.
                self.hass.async_create_background_task(
                    self.mgr.async_rebuild([day]), f"spotify_weekmix rebuild {day}")
            return result
        schema = vol.Schema({
            vol.Optional("target"): sel.TextSelector(),
            vol.Optional("description"): sel.TextSelector(),
            vol.Optional("sources"): TEXT_LIST,
            vol.Optional("searches"): TEXT_LIST,
            vol.Optional("seeds"): TEXT_LIST,
            vol.Optional("min_year"): _num(1900, 2100),
            vol.Optional("max_rap"): _num(0, 500),
            vol.Optional("seed_weeks"): _num(1, 12),
            vol.Optional("rebuild_now", default=False): sel.BooleanSelector(),
        })
        suggested = {
            "target": cfg.get("target", ""), "description": cfg.get("description", ""),
            "sources": _join(cfg.get("sources")), "searches": _join(cfg.get("searches")),
            "seeds": _join(f"https://open.spotify.com/track/{t}" for t in cfg.get("seeds", [])),
            "min_year": cfg.get("min_year"), "max_rap": cfg.get("max_rap"),
            "seed_weeks": cfg.get("seed_weeks"),
        }
        return self.async_show_form(
            step_id="day", data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in suggested.items() if v not in (None,)}),
            description_placeholders={"day": day.capitalize(), "seeds": str(len(cfg.get("seeds", [])))})

    # --- blocklists ---
    LISTS = ["block_artists", "block_tracks", "allow_artists", "block_genres", "block_terms", "rap_genres"]

    async def async_step_blocklists(self, user_input=None) -> ConfigFlowResult:
        s = self.mgr.settings
        if user_input is not None:
            def mutate(st):
                for k in self.LISTS:
                    st[k] = _lines(user_input.get(k))
            return await self._save(mutate)
        schema = vol.Schema({vol.Optional(k): TEXT_LIST for k in self.LISTS})
        return self.async_show_form(
            step_id="blocklists",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: _join(s.get(k)) for k in self.LISTS}))

    # --- algemeen ---
    async def async_step_general(self, user_input=None) -> ConfigFlowResult:
        g = self.mgr.settings["general"]
        ints = ["personal_max", "search_pages", "min_popularity", "max_per_artist",
                "artist_gap", "rest_days", "seed_weeks"]
        if user_input is not None:
            def mutate(s):
                gg = s["general"]
                gg["target_hours"] = float(user_input["target_hours"])
                for k in ints:
                    gg[k] = int(user_input[k])
                gg["unique_titles"] = bool(user_input["unique_titles"])
                gg["covers"] = bool(user_input["covers"])
                gg["market"] = user_input["market"].strip().upper()
                gg["playlist_name"] = user_input["playlist_name"]
            return await self._save(mutate)
        schema = vol.Schema({
            vol.Required("target_hours", default=g["target_hours"]): _num(1, 24, 0.5, "h"),
            vol.Required("max_per_artist", default=g["max_per_artist"]): _num(1, 50),
            vol.Required("artist_gap", default=g["artist_gap"]): _num(0, 200),
            vol.Required("rest_days", default=g["rest_days"]): _num(0, 180, 1, "d"),
            vol.Required("seed_weeks", default=g["seed_weeks"]): _num(1, 12),
            vol.Required("unique_titles", default=g["unique_titles"]): sel.BooleanSelector(),
            vol.Required("covers", default=g.get("covers", True)): sel.BooleanSelector(),
            vol.Required("min_popularity", default=g["min_popularity"]): _num(0, 100),
            vol.Required("personal_max", default=g["personal_max"]): _num(0, 200),
            vol.Required("search_pages", default=g["search_pages"]): _num(1, 19),
            vol.Required("market", default=g["market"]): sel.TextSelector(),
            vol.Required("playlist_name", default=g["playlist_name"]): sel.TextSelector(),
        })
        # '{dag}' in het label is voor HA een variabele: zelf invullen, anders een vertaalfout.
        return self.async_show_form(step_id="general", data_schema=schema,
                                    description_placeholders={"dag": "{dag}"})
