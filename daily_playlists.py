"""
daily_playlists.py — command-line versie van Spotify Weekmix.

De eigenlijke logica staat in custom_components/spotify_weekmix/engine.py; die
wordt ook door de Home Assistant-integratie gebruikt. Dit script is er om op
de NAS te testen en met de hand te draaien.

Instellingen: settings.json naast dit script als die bestaat, anders de
standaard (custom_components/spotify_weekmix/defaults.json). Geheugen (wat speelde
wanneer): history.json naast dit script.

Gebruik:
    .venv/bin/python daily_playlists.py                  # lijst van VANDAAG
    .venv/bin/python daily_playlists.py --day maandag
    .venv/bin/python daily_playlists.py --all            # alle 7 dagen
    .venv/bin/python daily_playlists.py --check          # login + config
    .venv/bin/python daily_playlists.py --all --dry-run  # niets aanpassen

LET OP: draait de HA-integratie met 'Automatisch verversen' aan, dan heeft die
een EIGEN geheugen (in HA). Een handmatige run hier overschrijft de playlists
wel; HA ziet die nummers bij de volgende run alsnog als gespeeld (via de
'toegevoegd op'-datum), maar gebruik op de NAS bij voorkeur --dry-run.
"""

import argparse
import datetime
import importlib.util
import json
import os
import time

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyOAuth

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENT = os.path.join(HERE, "custom_components", "spotify_weekmix")

# engine.py laden zonder het HA-pakket (__init__.py importeert homeassistant).
_spec = importlib.util.spec_from_file_location("spotify_weekmix_engine", os.path.join(COMPONENT, "engine.py"))
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

SCRIPT_VERSION = engine.ENGINE_VERSION
WEEKDAYS = engine.WEEKDAYS


def _load_dotenv(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv(os.path.join(HERE, ".env"))

SETTINGS_PATH = os.environ.get("SPOTIFY_SETTINGS", os.path.join(HERE, "settings.json"))
DEFAULTS_PATH = os.path.join(COMPONENT, "defaults.json")
HISTORY_PATH = os.environ.get("SPOTIFY_HISTORY", os.path.join(HERE, "history.json"))
CACHE_PATH = os.environ.get("SPOTIPY_CACHE", os.path.join(HERE, ".cache"))
REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPE = ("playlist-read-private playlist-modify-private playlist-modify-public "
         "user-top-read user-read-recently-played user-library-read")

_sp = None


def client() -> Spotify:
    global _sp
    if _sp is None:
        cid, secret = os.environ.get("SPOTIFY_CLIENT_ID"), os.environ.get("SPOTIFY_CLIENT_SECRET")
        if not cid or not secret:
            raise SystemExit("Ontbrekende Spotify-gegevens. Zet SPOTIFY_CLIENT_ID en "
                             "SPOTIFY_CLIENT_SECRET in .env (zie .env.example).")
        _sp = Spotify(
            auth_manager=SpotifyOAuth(client_id=cid, client_secret=secret, redirect_uri=REDIRECT_URI,
                                      scope=SCOPE, open_browser=False,
                                      cache_handler=CacheFileHandler(cache_path=CACHE_PATH)),
            requests_timeout=20, retries=5)
    return _sp


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_settings() -> dict:
    return load_json(SETTINGS_PATH, None) or load_json(DEFAULTS_PATH, None)


def build_day(day: str, dry_run: bool = False, today: datetime.date | None = None,
              history: dict | None = None) -> dict:
    """Bouwt één dag. `history` meegeven = in-memory (voor simulaties); anders history.json."""
    settings = load_settings()
    own = history is None
    if own:
        history = load_json(HISTORY_PATH, {}).get("plays", {})
    eng = engine.MixEngine(client(), settings, history)
    result = eng.build_day(day, today=today, dry_run=dry_run)
    if not dry_run and own:
        save_json(HISTORY_PATH, {"version": 1, "plays": history})
    if not dry_run and eng.settings_changed:
        save_json(SETTINGS_PATH, settings)
    return result


def today_name() -> str:
    return WEEKDAYS[datetime.date.today().weekday()]


def _with_retries(fn, tries: int = 4, delay: int = 5):
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except RequestException as e:
            if attempt == tries:
                raise
            print(f"  netwerkfout ({type(e).__name__}), poging {attempt}/{tries} — opnieuw over {delay}s ...")
            time.sleep(delay)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--day", choices=WEEKDAYS)
    p.add_argument("--all", action="store_true")
    p.add_argument("--check", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="alles berekenen, geen playlist aanpassen")
    args = p.parse_args()

    if args.check:
        for line in engine.MixEngine(client(), load_settings(), {}).check():
            print(line)
    elif args.all:
        for d in WEEKDAYS:
            try:
                _with_retries(lambda day=d: build_day(day, args.dry_run))
            except Exception as e:  # noqa: BLE001
                print(f"[{d}] MISLUKT na retries: {e} — doorgegaan met de volgende dag.")
    else:
        _with_retries(lambda: build_day(args.day or today_name(), args.dry_run))


if __name__ == "__main__":
    main()
