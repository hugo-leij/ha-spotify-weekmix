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


def make_entry(hass, scope="playlist-modify-private ugc-image-upload"):
    e = MockConfigEntry(
        domain=DOMAIN, title="Saints", unique_id="saints",
        data={"auth_implementation": "cred",
              "token": {"access_token": "at", "refresh_token": "rt", "token_type": "Bearer",
                        "expires_in": 3600, "expires_at": time.time() + 3600, "scope": scope}})
    e.add_to_hass(hass)
    return e


@pytest.fixture
def entry(hass: HomeAssistant, creds) -> MockConfigEntry:
    return make_entry(hass)


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
    assert res == {"artist": "Eves Laurent", "removing_from_playlists": True}
    await hass.async_block_till_done(wait_background_tasks=True)
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
    await hass.async_block_till_done(wait_background_tasks=True)
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


async def test_auto_refresh_switch_schedules_daily_run(hass, entry, built, freezer):
    # Klok vastzetten: met de echte klok was deze test af en toe rood op GitHub.
    import datetime as _dt
    tz = dt_util.get_default_time_zone()
    # Vandaag 03:00 (niet een vaste datum: dan zou het test-token al verlopen zijn).
    base = dt_util.now().astimezone(tz).replace(hour=3, minute=0, second=0, microsecond=0)
    freezer.move_to(base)
    # Token lang geldig maken: de vastgezette klok mag het niet laten verlopen.
    hass.config_entries.async_update_entry(entry, data={**entry.data, "token": {
        **entry.data["token"], "expires_at": base.timestamp() + 10 * 86400}})
    mgr = await setup(hass, entry)
    switch = next(s.entity_id for s in hass.states.async_all("switch"))
    await mgr.async_update_settings(lambda s: s["ha"].update(refresh_time="05:30:00"))
    await hass.services.async_call("switch", "turn_on", {"entity_id": switch}, blocking=True)
    assert hass.states.get(switch).state == "on"
    fire = base.replace(hour=5, minute=30)
    freezer.move_to(fire)
    async_fire_time_changed(hass, fire)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert built == [(["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag",
                       "zondag"][fire.weekday()], False)]
    # uitzetten -> geen run meer
    await hass.services.async_call("switch", "turn_off", {"entity_id": switch}, blocking=True)
    nxt = fire + _dt.timedelta(days=1)
    freezer.move_to(nxt)
    async_fire_time_changed(hass, nxt)
    await hass.async_block_till_done(wait_background_tasks=True)
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
        "target_hours", "max_per_artist", "artist_gap", "rest_days", "seed_weeks", "unique_titles", "covers",
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


async def test_old_login_without_cover_scope_asks_reauth_once(hass, creds, built):
    entry = make_entry(hass, scope="playlist-modify-private")        # login van vóór 0.2.0
    await setup(hass, entry)
    for _ in range(2):
        await hass.services.async_call(DOMAIN, "rebuild", {"day": "monday"}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    flows = [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth"]
    assert len(flows) == 1 and len(built) == 2        # verversen gaat gewoon door


async def test_login_with_cover_scope_no_reauth(hass, entry, built):
    await setup(hass, entry)
    await hass.services.async_call(DOMAIN, "rebuild", {"day": "monday"}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    assert not [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth"]


async def test_day_form_rebuild_now(hass, entry, built):
    mgr = await setup(hass, entry)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "day_select"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"day": "vrijdag"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "target": mgr.settings["days"]["vrijdag"]["target"], "searches": "party genre:dance-pop",
        "rebuild_now": True})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    # De opbouw loopt als achtergrondtaak: daar expliciet op wachten (anders flaky).
    await hass.async_block_till_done(wait_background_tasks=True)
    assert built == [("vrijdag", False)]
    assert mgr.settings["days"]["vrijdag"]["searches"] == ["party genre:dance-pop"]


async def test_token_without_scope_field_tries_covers_without_reauth(hass, creds, built):
    entry = make_entry(hass, scope=None)
    del entry.data["token"]["scope"]
    mgr = await setup(hass, entry)
    assert mgr._has_cover_scope()
    await hass.services.async_call(DOMAIN, "rebuild", {"day": "monday"}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    assert not [f for f in hass.config_entries.flow.async_progress() if f["context"]["source"] == "reauth"]


def test_existing_install_gets_new_default_list_items_once():
    from custom_components.spotify_weekmix.manager import load_defaults, merge_defaults
    defaults = load_defaults()
    old = {k: v for k, v in defaults.items() if k not in ("defaults_version", "block_scripts")}
    old = __import__("copy").deepcopy(old)
    old["block_genres"] = [g for g in old["block_genres"] if g not in ("children's music", "lullaby")] + ["eigen genre"]
    merged = merge_defaults(old, defaults)
    assert "children's music" in merged["block_genres"] and "eigen genre" in merged["block_genres"]
    assert merged["block_scripts"] and merged["defaults_version"] == 2
    # gebruiker haalt het weer weg -> komt niet terug bij een volgende start
    merged["block_genres"].remove("lullaby")
    again = merge_defaults(merged, defaults)
    assert "lullaby" not in again["block_genres"]
    assert again["block_genres"].count("children's music") == 1


async def test_blocklists_form_saves_scripts(hass, entry):
    mgr = await setup(hass, entry)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"next_step_id": "blocklists"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {
        "block_scripts": ["chinese", "arabic"], "block_artists": "A", "block_genres": "phonk"})
    assert r["type"] is FlowResultType.CREATE_ENTRY
    assert mgr.settings["block_scripts"] == ["chinese", "arabic"]


# ---------------- laatst gespeeld (0.4.0) ----------------

def _play(hass, entity, tid, title, artist, state="playing"):
    hass.states.async_set(entity, state, {
        "media_content_id": f"x-sonos-spotify:spotify%3atrack%3a{tid}?sid=9&flags=8224&sn=1",
        "media_title": title, "media_artist": artist})


def _recent(hass):
    st = hass.states.get("sensor.spotify_weekmix_saints_recently_played")
    return st, st.attributes.get("tracks", [])


async def test_recently_played_from_players_without_api(hass, entry, removed):
    mgr = await setup(hass, entry)
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.woonkamer", "media_player.keuken"]))
    mgr.reschedule()
    ids = [f"{i:022d}" for i in range(1, 14)]
    for i, tid in enumerate(ids):
        _play(hass, "media_player.woonkamer", tid, f"Song {i}", f"Artist {i}, Gast")
        _play(hass, "media_player.keuken", tid, f"Song {i}", f"Artist {i}, Gast")   # gegroepeerd: zelfde nummer
        await hass.async_block_till_done()
    hass.states.async_set("media_player.woonkamer", "playing", {"media_content_id": "x-rincon-mp3radio://radio", "media_title": "Radio 2"})
    _play(hass, "media_player.woonkamer", ids[-1], "Song 12", "Artist 12", state="paused")
    await hass.async_block_till_done()
    st, tracks = _recent(hass)
    assert st.state == "Artist 12, Gast – Song 12"
    assert len(tracks) == 10 and tracks[0]["track_id"] == ids[-1] and tracks[-1]["track_id"] == ids[3]
    assert tracks[0]["uri"] == f"spotify:track:{ids[-1]}" and not tracks[0]["blocked"]
    # blokkeren vanuit de lijst -> attribuut laat het zien
    await hass.services.async_call(DOMAIN, "block_track", {"track": tracks[1]["uri"]}, blocking=True, return_response=True)
    await hass.services.async_call(DOMAIN, "block_artist", {"artist": "Artist 10"}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    _, tracks = _recent(hass)
    assert tracks[1]["blocked"] and tracks[2]["artist_blocked"] and not tracks[0]["blocked"]
    # en weer toestaan
    await hass.services.async_call(DOMAIN, "unblock_track", {"track": tracks[1]["url"]}, blocking=True, return_response=True)
    await hass.async_block_till_done()
    _, tracks = _recent(hass)
    assert not tracks[1]["blocked"]


async def test_recently_played_survives_reload(hass, entry):
    mgr = await setup(hass, entry)
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.woonkamer"]))
    mgr.reschedule()
    _play(hass, "media_player.woonkamer", "4uLU6hMCjMI75M1A2tKUQC", "Blinding Lights", "The Weeknd")
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    _, tracks = _recent(hass)
    assert tracks and tracks[0]["title"] == "Blinding Lights"


async def test_no_players_configured_no_listening(hass, entry):
    await setup(hass, entry)
    _play(hass, "media_player.woonkamer", "4uLU6hMCjMI75M1A2tKUQC", "X", "Y")
    await hass.async_block_till_done()
    st, tracks = _recent(hass)
    assert tracks == [] and st.state in ("unknown", None)



async def test_block_returns_before_spotify_removal_finishes(hass, entry):
    """De knop/sensor mag niet wachten op het weghalen uit de playlists (~15 s)."""
    import asyncio
    import threading
    gate = threading.Event()
    calls = []

    def slow_remove(self, **kw):
        gate.wait(5)                     # Spotify 'hangt' tot we het vrijgeven
        calls.append(kw)
        return 1

    mgr = await setup(hass, entry)
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.woonkamer"]))
    mgr.reschedule()
    nxt = async_mock_service(hass, "media_player", "media_next_track")
    _play(hass, "media_player.woonkamer", "4uLU6hMCjMI75M1A2tKUQC", "Blinding Lights", "The Weeknd")
    await hass.async_block_till_done()
    with patch.object(MixEngine, "remove_from_lists", slow_remove):
        res = await asyncio.wait_for(hass.services.async_call(
            DOMAIN, "block_track", {}, blocking=True, return_response=True), timeout=2)
        assert res["removing_from_playlists"] is True
        _, tracks = _recent(hass)
        assert tracks[0]["blocked"] and len(nxt) == 1 and calls == []   # al rood + overgeslagen
        gate.set()
        await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == [{"track_uri": "spotify:track:4uLU6hMCjMI75M1A2tKUQC"}]


async def test_background_removal_error_shows_on_status(hass, entry):
    def boom(self, **kw):
        raise RuntimeError("Spotify stuk")

    await setup(hass, entry)
    with patch.object(MixEngine, "remove_from_lists", boom):
        await hass.services.async_call(DOMAIN, "block_artist", {"artist": "X"}, blocking=True, return_response=True)
        await hass.async_block_till_done(wait_background_tasks=True)
    st = hass.states.get("sensor.spotify_weekmix_saints_status")
    assert st.state == "error" and "Spotify stuk" in st.attributes["last_error"]



async def test_recent_image_is_fixed_spotify_cover_not_player_proxy(hass, entry, aioclient_mock):
    aioclient_mock.get("https://open.spotify.com/oembed", json={
        "thumbnail_url": "https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02aaaa"})
    mgr = await setup(hass, entry)
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.woonkamer"]))
    mgr.reschedule()
    hass.states.async_set("media_player.woonkamer", "playing", {
        "media_content_id": "x-sonos-spotify:spotify%3atrack%3a4uLU6hMCjMI75M1A2tKUQC?sid=9",
        "media_title": "Blinding Lights", "media_artist": "The Weeknd",
        "entity_picture": "/api/media_player_proxy/media_player.woonkamer?token=abc&cache=1"})
    await hass.async_block_till_done()
    _, tracks = _recent(hass)
    assert tracks[0]["image"] == "https://image-cdn-ak.spotifycdn.com/image/ab67616d00001e02aaaa"
    assert "media_player_proxy" not in str(tracks)


async def test_recent_image_falls_back_to_web_api(hass, entry, aioclient_mock):
    aioclient_mock.get("https://open.spotify.com/oembed", status=500)

    class FakeSp:
        def track(self, tid):
            return {"album": {"images": [{"url": "https://i.scdn.co/640"}, {"url": "https://i.scdn.co/300"},
                                         {"url": "https://i.scdn.co/64"}]}}

    mgr = await setup(hass, entry)
    await mgr.async_update_settings(lambda s: s["ha"].update(media_players=["media_player.woonkamer"]))
    mgr.reschedule()

    async def fake_client():
        return FakeSp()

    mgr._client = fake_client
    _play(hass, "media_player.woonkamer", "4uLU6hMCjMI75M1A2tKUQC", "Blinding Lights", "The Weeknd")
    await hass.async_block_till_done()
    _, tracks = _recent(hass)
    assert tracks[0]["image"] == "https://i.scdn.co/300"


async def test_old_proxy_images_replaced_on_startup(hass, entry, aioclient_mock):
    aioclient_mock.get("https://open.spotify.com/oembed", json={"thumbnail_url": "https://i.scdn.co/fixed"})
    mgr = await setup(hass, entry)
    mgr.recent = [{"track_id": "4uLU6hMCjMI75M1A2tKUQC", "uri": "spotify:track:4uLU6hMCjMI75M1A2tKUQC",
                   "url": "https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC",
                   "title": "X", "artist": "Y", "image": "/api/media_player_proxy/x?token=1"}]
    await mgr.async_save()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    _, tracks = _recent(hass)
    assert tracks[0]["image"] == "https://i.scdn.co/fixed"
