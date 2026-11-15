"""Integratietests: setup, entiteiten, services, opties en OAuth-flow in een echte HA-testomgeving."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed, async_mock_service

from custom_components.spotify_weekmix.const import DOMAIN, OAUTH2_AUTHORIZE, OAUTH2_TOKEN
from custom_components.spotify_weekmix.engine import MixEngine

CLIENT_ID, CLIENT_SECRET = "cid", "secret"


def fake_result(day, **kw):
    r = dict(day=day, date="2026-11-18", target="spotify:playlist:x", tracks=320, hours=18.0,
             artists=250, max_per_artist=4, same_artist_within_5=0, seeds_used=0, seeds_total=0,
             repeats=0, short=False, dry_run=False, version="t", uris=["spotify:track:1"])
    r.update(kw)
    return r


@pytest.fixture
async def creds(hass: HomeAssistant):
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET), "cred")


@pytest.fixture
def entry(hass: HomeAssistant, creds) -> MockConfigEntry:
    e = MockConfigEntry(
        domain=DOMAIN, title="Saints", unique_id="saints",
        data={"auth_implementation": "cred",
              "token": {"access_token": "at", "refresh_token": "rt", "token_type": "Bearer",
                        "expires_in": 3600, "expires_at": time.time() + 3600}})
    e.add_to_hass(hass)
    return e


@pytest.fixture
def built():
    calls = []

    def fake_build(self, day, today=None, dry_run=False):
        calls.append((day, dry_run))
        return fake_result(day, dry_run=dry_run)

    with patch.object(MixEngine, "build_day", fake_build):
        yield calls


@pytest.fixture
def removed():
    calls = []

    def fake_remove(self, **kw):
        calls.append(kw)
        return 3

    with patch.object(MixEngine, "remove_from_lists", fake_remove):
        yield calls


async def setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def test_setup_creates_entities(hass, entry, built):
    mgr = await setup(hass, entry)
    states = {s.entity_id for s in hass.states.async_all()}
    for day in ("monday", "wednesday", "sunday"):
        assert any(e.startswith("sensor.") and e.endswith("_" + day) for e in states), day
    assert {"button.spotify_weekmix_saints_rebuild_today",
            "button.spotify_weekmix_saints_never_this_artist_again",
            "button.spotify_weekmix_saints_never_this_track_again",
            "switch.spotify_weekmix_saints_automatic_daily_refresh",
            "sensor.spotify_weekmix_saints_status"} <= states, sorted(states)
    assert not any("maandag" in e or "nooit" in e for e in states)
    assert any(e.startswith("switch.") for e in states)
    # standaardinstellingen geladen, automatisch verversen staat standaard UIT
    assert len(mgr.settings["days"]["woensdag"]["seeds"]) == 345
    assert mgr.ha["auto_refresh"] is False
    assert built == []


async def test_rebuild_service_and_sensor(hass, entry, built):
    mgr = await setup(hass, entry)
    res = await hass.services.async_call(DOMAIN, "rebuild", {"day": "wednesday"}, blocking=True, return_response=True)
    assert built == [("woensdag", False)]
    assert res["results"]["wednesday"]["tracks"] == 320 and "uris" not in res["results"]["wednesday"]
    assert res["results"]["wednesday"]["day"] == "wednesday"
    # entity-ID's zijn Engels (HA maakt ze uit de Engelse vertaling)
    sensor = next(s for s in hass.states.async_all("sensor") if s.entity_id.endswith("_wednesday"))
    assert sensor.attributes["tracks"] == 320 and sensor.state not in ("unknown", "unavailable")
    # opgeslagen in .storage
    assert mgr.results["woensdag"]["hours"] == 18.0


async def test_rebuild_all_and_dry_run_does_not_store(hass, entry, built):
    mgr = await setup(hass, entry)
    await hass.services.async_call(DOMAIN, "rebuild", {"day": "all", "dry_run": True}, blocking=True, return_response=True)
    assert [d for d, _ in built] == ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]
    assert all(dr for _, dr in built) and mgr.results == {}


async def test_rebuild_error_is_reported_not_raised(hass, entry):
    def boom(self, day, today=None, dry_run=False):
        raise RuntimeError("API stuk")

    await setup(hass, entry)
    with patch.object(MixEngine, "build_day", boom):
        # Nederlandse waarde blijft werken als alias
        res = await hass.services.async_call(DOMAIN, "rebuild", {"day": "maandag"}, blocking=True, return_response=True)
    assert "API stuk" in res["results"]["monday"]["error"]
    status = next(s for s in hass.states.async_all("sensor") if s.entity_id.endswith("status"))
    assert status.state == "error" and "API stuk" in status.attributes["last_error"]


async def test_shuffle_off_after_rebuild(hass, entry, built):
    mgr = await setup(hass, entry)
    shuffle = async_mock_service(hass, "media_player", "shuffle_set")
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.woonkamer"]))
    await hass.services.async_call(DOMAIN, "rebuild", {"day": "maandag"}, blocking=True, return_response=True)
    assert len(shuffle) == 1 and shuffle[0].data == {"entity_id": "media_player.woonkamer", "shuffle": False}


async def test_block_current_artist_from_player(hass, entry, removed):
    mgr = await setup(hass, entry)
    nxt = async_mock_service(hass, "media_player", "media_next_track")
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.woonkamer"]))
    hass.states.async_set("media_player.woonkamer", "playing",
                          {"media_artist": "Eves Laurent, Kevin", "media_title": "SOFT LEVEN"})
    res = await hass.services.async_call(DOMAIN, "block_artist", {}, blocking=True, return_response=True)
    assert res == {"artist": "Eves Laurent", "removed": 3}
    assert mgr.settings["block_artists"].count("Eves Laurent") == 1      # stond er al: niet dubbel
    assert removed == [{"artist": "Eves Laurent"}]
    assert len(nxt) == 1


async def test_block_artist_by_name_adds_once(hass, entry, removed):
    mgr = await setup(hass, entry)
    for _ in range(2):
        await hass.services.async_call(DOMAIN, "block_artist", {"artist": "Nieuwe Artiest"}, blocking=True, return_response=True)
    assert mgr.settings["block_artists"].count("Nieuwe Artiest") == 1
    await hass.services.async_call(DOMAIN, "unblock_artist", {"artist": "nieuwe artiest"}, blocking=True, return_response=True)
    assert "Nieuwe Artiest" not in mgr.settings["block_artists"]


async def test_block_current_track_sonos_and_seed_removed(hass, entry, removed):
    mgr = await setup(hass, entry)
    seed = mgr.settings["days"]["woensdag"]["seeds"][0]
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.keuken"], skip_on_block=False))
    hass.states.async_set("media_player.keuken", "playing", {
        "media_artist": "Some One", "media_title": "Song (Radio Edit)",
        "media_content_id": f"x-sonos-spotify:spotify%3atrack%3a{seed}?sid=9&flags=8224&sn=1"})
    res = await hass.services.async_call(DOMAIN, "block_track", {}, blocking=True, return_response=True)
    assert f"spotify:track:{seed}" in res["blocked"] and "some one|song" in res["blocked"]
    assert seed not in mgr.settings["days"]["woensdag"]["seeds"]
    assert removed == [{"track_uri": f"spotify:track:{seed}"}]


async def test_block_without_player_gives_clear_error(hass, entry):
    await setup(hass, entry)
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError, match="No player"):
        await hass.services.async_call(DOMAIN, "block_artist", {}, blocking=True, return_response=True)


async def test_settings_persist_across_reload(hass, entry, removed):
    await setup(hass, entry)
    await hass.services.async_call(DOMAIN, "block_artist", {"artist": "Blijf Weg"}, blocking=True, return_response=True)
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert "Blijf Weg" in entry.runtime_data.settings["block_artists"]


async def test_auto_refresh_switch_schedules_daily_run(hass, entry, built):
    mgr = await setup(hass, entry)
    switch = next(s.entity_id for s in hass.states.async_all("switch"))
    await mgr.async_update_settings(lambda s: s["ha"].update(refresh_time="05:30:00"))
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert hass.states.get(switch).state == "on"
    now = dt_util.now()
    fire = now.replace(hour=5, minute=30, second=0, microsecond=0)
    if fire <= now:
        fire = fire + __import__("datetime").timedelta(days=1)
    async_fire_time_changed(hass, fire)
    await hass.async_block_till_done()
    assert len(built) == 1 and built[0][0] == ["maandag", "dinsdag", "woensdag", "donderdag",
                                               "vrijdag", "zaterdag", "zondag"][fire.weekday()]
    # uitzetten -> geen run meer
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    async_fire_time_changed(hass, fire + __import__("datetime").timedelta(days=1))
    await hass.async_block_till_done()
    assert len(built) == 1


async def test_options_flow_all_steps(hass, entry):
    mgr = await setup(hass, entry)
    # spelers & planning
    r = await hass.config_entries.options.async_init(entry.entry_id)
    assert r["type"] is FlowResultType.MENU
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "players"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "media_players": ["media_player.woonkamer"], "auto_refresh": False, "refresh_time": "06:15:00",
        "shuffle_off": True, "skip_on_block": False})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert mgr.ha["refresh_time"] == "06:15:00" and mgr.ha["media_players"] == ["media_player.woonkamer"]
    # een dag
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "day_select"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"day": "dinsdag"})
    assert r["step_id"] == "day"
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "target": "spotify:playlist:abc", "sources": "https://open.spotify.com/playlist/5Ka3zhsTJsiYAe5kcn7dln?si=1\n",
        "searches": "happy genre:pop\n\nfeel good genre:indie-pop",
        "seeds": "# mijn favorieten\nhttps://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC\nonzin",
        "min_year": 2010})
    d = mgr.settings["days"]["dinsdag"]
    assert d["sources"] == ["5Ka3zhsTJsiYAe5kcn7dln"]
    assert d["searches"] == ["happy genre:pop", "feel good genre:indie-pop"]
    assert d["seeds"] == ["4uLU6hMCjMI75M1A2tKUQC"] and d["min_year"] == 2010 and d["max_rap"] is None
    # blocklists
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "blocklists"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "block_artists": "A\nB", "block_tracks": "", "allow_artists": "Madonna", "block_genres": "phonk",
        "block_terms": "yoga", "rap_genres": "rap"})
    assert mgr.settings["block_artists"] == ["A", "B"] and mgr.settings["block_tracks"] == []
    # algemeen
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "general"})
    g = dict(mgr.settings["general"])
    g.update(target_hours=14, max_per_artist=3, market="be")
    r = await hass.config_entries.options.async_configure(r["flow_id"], {k: g[k] for k in (
        "target_hours", "max_per_artist", "artist_gap", "rest_days", "seed_weeks", "unique_titles",
        "min_popularity", "personal_max", "search_pages", "market", "playlist_name")})
    assert mgr.settings["general"]["target_hours"] == 14 and mgr.settings["general"]["market"] == "BE"


@pytest.mark.usefixtures("current_request_with_host")
async def test_oauth_config_flow(hass, creds, hass_client_no_auth, aioclient_mock):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": "https://example.com/auth/external/callback"})
    assert result["url"].startswith(OAUTH2_AUTHORIZE)
    assert "show_dialog=true" in result["url"] and "user-top-read" in result["url"].replace("%20", " ").replace("+", " ")
    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200
    aioclient_mock.post(OAUTH2_TOKEN, json={"refresh_token": "rt", "access_token": "at",
                                            "token_type": "Bearer", "expires_in": 3600})
    with patch("custom_components.spotify_weekmix.config_flow.Spotify.me",
               return_value={"id": "saints", "display_name": "Saints"}), \
         patch("custom_components.spotify_weekmix.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Saints" and result["result"].unique_id == "saints"
