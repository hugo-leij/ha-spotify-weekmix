"""LIVE test tegen de echte Spotify-API (alleen dry-run, schrijft niets).

Draait alleen met SPOTIFY_LIVE_CACHE=<pad naar een geldige spotipy .cache>:
    SPOTIFY_LIVE_CACHE=... pytest tests/test_live.py
"""

from __future__ import annotations

import json
import os

import pytest

from homeassistant.components.application_credentials import ClientCredential, async_import_client_credential
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spotify_weekmix.const import DOMAIN

CACHE = os.environ.get("SPOTIFY_LIVE_CACHE")
pytestmark = pytest.mark.skipif(not CACHE, reason="geen SPOTIFY_LIVE_CACHE")


@pytest.mark.parametrize("day", ["tuesday"])
async def test_live_dry_run(hass, socket_enabled, monkeypatch, day):
    # De testomgeving blokkeert DNS; voor deze ene live-test zetten we het terug.
    import socket
    import pytest_socket
    from pytest_homeassistant_custom_component import plugins
    monkeypatch.setattr(socket, "getaddrinfo", plugins._real_getaddrinfo)
    monkeypatch.setattr(socket.socket, "connect", pytest_socket._true_connect)
    with open(CACHE) as fh:  # noqa: ASYNC230 - testbestand, eenmalig
        token = json.load(fh)
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential(os.environ["SPOTIFY_CLIENT_ID"], os.environ["SPOTIFY_CLIENT_SECRET"]), "cred")
    entry = MockConfigEntry(domain=DOMAIN, title="Saints", unique_id="saints",
                            data={"auth_implementation": "cred", "token": token})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    res = await hass.services.async_call(DOMAIN, "rebuild", {"day": day, "dry_run": True},
                                         blocking=True, return_response=True)
    r = res["results"][day]
    print(r)
    assert "error" not in r, r
    assert r["tracks"] > 250 and r["hours"] >= 17.5 and r["max_per_artist"] <= 4
    assert r["same_artist_within_5"] == 0 and r["dry_run"] is True
