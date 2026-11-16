"""Unit-tests voor de motor, met een nep-Spotify (geen netwerk)."""

from __future__ import annotations

import collections
import copy
import datetime
import importlib.util
import json
import os
import random

import pytest

from .fake_spotify import FakeSpotify

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "engine_under_test", os.path.join(ROOT, "custom_components", "spotify_weekmix", "engine.py"))
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)

DEFAULTS = json.load(open(os.path.join(ROOT, "custom_components", "spotify_weekmix", "defaults.json")))
TODAY = datetime.date(2026, 11, 18)          # een woensdag


def settings(**general):
    s = copy.deepcopy(DEFAULTS)
    for d in s["days"].values():
        d.update(target="", sources=[], searches=[], seeds=[], min_year=None, max_rap=None)
    base = dict(target_hours=1, max_per_artist=4, artist_gap=3, rest_days=28,
                seed_weeks=2, personal_max=0, search_pages=19)
    base.update(general)
    s["general"].update(base)
    return s


def world(n_artists=40, per_artist=10, ms=180_000, **kw):
    """Een zoekterm 'pop' met n_artists × per_artist geldige nummers."""
    sp = FakeSpotify(**kw)
    uris = []
    for a in range(n_artists):
        art = sp.find_or_make_artist(f"Artiest {a}", genres=["pop"])
        for i in range(per_artist):
            uris.append(sp.add_track(f"Song {a}-{i}", [art], ms=ms)["uri"])
    random.Random(1).shuffle(uris)
    sp.search_results["pop"] = uris
    return sp


def build(sp, s, history=None, day="woensdag", today=TODAY, dry_run=False, covers=False):
    history = {} if history is None else history
    eng = engine.MixEngine(sp, s, history, log=lambda m: None, allow_covers=covers)
    s["days"][day]["searches"] = s["days"][day]["searches"] or ["pop"]
    if not s["days"][day]["target"]:
        s["days"][day]["target"] = f"spotify:playlist:{sp.make_playlist()}"
    sp.today = today.isoformat()
    return eng, eng.build_day(day, today=today, dry_run=dry_run)


# ---------------- basis ----------------

def test_fills_to_target_hours_without_duplicates():
    sp = world()
    s = settings()
    _, r = build(sp, s)
    assert 0.98 <= r["hours"] <= 1.1
    keys = [engine.song_key(sp.tracks_db[u]["artists"][0]["name"], sp.tracks_db[u]["name"]) for u in r["uris"]]
    assert len(keys) == len(set(keys))
    pid = s["days"]["woensdag"]["target"].split(":")[-1]
    assert [u for u, _ in sp.playlists[pid]["items"]] == r["uris"]


def test_dry_run_does_not_write():
    sp = world()
    s = settings()
    s["days"]["woensdag"]["target"] = f"spotify:playlist:{sp.make_playlist()}"
    pid = s["days"]["woensdag"]["target"].split(":")[-1]
    _, r = build(sp, s, dry_run=True)
    assert r["tracks"] > 0 and sp.playlists[pid]["items"] == []


def test_song_title_normalisation():
    assert engine.song_title("Don't Cry (Radio Version)") == "don't cry"
    assert engine.song_title("X - Remaster 2011") == "x"
    assert engine.song_title("(I Just) Died In Your Arms") == "(i just) died in your arms"


def test_track_id_parsing():
    t = "4uLU6hMCjMI75M1A2tKUQC"
    for s in (t, f"spotify:track:{t}", f"https://open.spotify.com/track/{t}?si=abc",
              f"x-sonos-spotify:spotify%3atrack%3a{t}?sid=9&flags=8224&sn=1"):
        assert engine.track_id(s) == t
    assert engine.track_id("# commentaar") == ""
    assert engine.track_id("spotify:playlist:abc") == ""


def test_same_release_variants_are_one_song():
    sp = FakeSpotify()
    a = sp.find_or_make_artist("A")
    u1 = sp.add_track("Don't Cry", [a])["uri"]
    u2 = sp.add_track("Don't Cry (Radio Version)", [a])["uri"]
    u3 = sp.add_track("Don't Cry - Remastered", [a])["uri"]
    sp.search_results["pop"] = [u1, u2, u3]
    s = settings(target_hours=5)
    _, r = build(sp, s)
    assert r["tracks"] == 1


def test_unique_titles_blocks_covers():
    sp = FakeSpotify()
    uris = [sp.add_track("Wicked Game", [sp.find_or_make_artist(n)])["uri"] for n in ("Chris Isaak", "LÖVEE", "VELA")]
    sp.search_results["pop"] = uris
    _, r = build(sp, settings(target_hours=5))
    assert r["tracks"] == 1
    _, r = build(sp, settings(target_hours=5, unique_titles=False))
    assert r["tracks"] == 3


# ---------------- artiesten ----------------

def test_max_per_artist_and_spread():
    sp = world(n_artists=10, per_artist=20)
    s = settings(target_hours=2, max_per_artist=4, artist_gap=20)
    _, r = build(sp, s)
    c = collections.Counter(sp.tracks_db[u]["artists"][0]["name"] for u in r["uris"])
    assert max(c.values()) <= 4
    names = [sp.tracks_db[u]["artists"][0]["name"] for u in r["uris"]]
    for i, n in enumerate(names):
        assert n not in names[max(0, i - 5):i], f"{n} te dicht op elkaar op plek {i}"


def test_cap_is_lifted_rather_than_short_day():
    sp = world(n_artists=2, per_artist=30)
    _, r = build(sp, settings(target_hours=1, max_per_artist=4))
    assert not r["short"] and r["max_per_artist"] > 4


@pytest.mark.parametrize("seed", range(50))
def test_spread_never_clusters_with_realistic_gap(seed):
    uris = [f"u{a}_{i}" for a in range(30) for i in range(4)] + [f"s{i}" for i in range(200)]
    art = {u: u.split("_")[0] for u in uris}
    names = [art[u] for u in engine.spread_order(uris, art, random.Random(seed), gap=20)]
    assert not any(n in names[max(0, i - 5):i] for i, n in enumerate(names))


def test_spread_order_is_permutation():
    uris = [f"u{i}" for i in range(100)]
    art = {u: f"a{i % 7}" for i, u in enumerate(uris)}
    out = engine.spread_order(uris, art, random.Random(3), gap=5)
    assert sorted(out) == sorted(uris)


# ---------------- filters ----------------

def test_blocked_artist_genre_term_popularity_script():
    sp = FakeSpotify()
    good = sp.add_track("Fine", [sp.find_or_make_artist("Goed", ["pop"])])["uri"]
    bad = [
        sp.add_track("Bla", [sp.find_or_make_artist("Frenna")])["uri"],                 # artiest
        sp.add_track("Hard", [sp.find_or_make_artist("X", ["hardstyle"])])["uri"],       # genre
        sp.add_track("Yoga Flow", [sp.find_or_make_artist("Y")])["uri"],                 # term
        sp.add_track("Filler", [sp.find_or_make_artist("Z")], pop=3)["uri"],              # populariteit
        sp.add_track("東京", [sp.find_or_make_artist("Q")])["uri"],                       # schrift
        sp.add_track("Duet", [sp.find_or_make_artist("Iemand"), sp.find_or_make_artist("Frenna")])["uri"],  # collab
    ]
    sp.search_results["pop"] = [good, *bad]
    _, r = build(sp, settings(target_hours=5))
    assert r["uris"] == [good]


def test_allow_artists_overrides_genre_only():
    sp = FakeSpotify()
    mad = sp.find_or_make_artist("Madonna")
    u = sp.add_track("Read My Lips", [mad, sp.find_or_make_artist("Feid", ["reggaeton"])])["uri"]
    sp.search_results["pop"] = [u]
    _, r = build(sp, settings(target_hours=5))
    assert r["uris"] == [u]


def test_block_tracks_by_uri_and_by_song_key():
    sp = FakeSpotify()
    a = sp.find_or_make_artist("A")
    u1 = sp.add_track("Weg", [a])["uri"]
    u2 = sp.add_track("Ook Weg (Live)", [a])["uri"]
    u3 = sp.add_track("Blijft", [a])["uri"]
    sp.search_results["pop"] = [u1, u2, u3]
    s = settings(target_hours=5)
    s["block_tracks"] = [u1, "a|ook weg"]
    _, r = build(sp, s)
    assert r["uris"] == [u3]


def test_seeds_bypass_filters_but_not_block_tracks():
    sp = FakeSpotify()
    seed_ok = sp.add_track("Hand", [sp.find_or_make_artist("Frenna")], pop=1)
    seed_blocked = sp.add_track("Nee", [sp.find_or_make_artist("B")])
    s = settings(target_hours=5, seed_weeks=1)
    s["days"]["woensdag"]["seeds"] = [seed_ok["id"], f"https://open.spotify.com/track/{seed_blocked['id']}"]
    s["block_tracks"] = [seed_blocked["uri"]]
    _, r = build(sp, s)
    assert r["uris"] == [seed_ok["uri"]]


def test_rap_cap():
    sp = FakeSpotify()
    rap = [sp.add_track(f"R{i}", [sp.find_or_make_artist(f"Rapper{i}", ["dutch hip hop"])])["uri"] for i in range(10)]
    pop = [sp.add_track(f"P{i}", [sp.find_or_make_artist(f"Pop{i}", ["pop"])])["uri"] for i in range(10)]
    sp.search_results["pop"] = rap + pop
    s = settings(target_hours=5)
    s["days"]["woensdag"]["max_rap"] = 2
    _, r = build(sp, s)
    assert sum(1 for u in r["uris"] if u in rap) == 2


# ---------------- geheugen / herhaling ----------------

def test_history_prevents_repeats_week_to_week():
    sp = world(n_artists=60, per_artist=10)       # ruim genoeg materiaal
    s = settings(target_hours=3)
    hist = {}
    _, r1 = build(sp, s, hist, today=TODAY)
    _, r2 = build(sp, s, hist, today=TODAY + datetime.timedelta(days=7))
    assert not set(r1["uris"]) & set(r2["uris"])
    assert r2["repeats"] == 0


def test_history_uses_oldest_first_when_material_runs_out():
    sp = world(n_artists=20, per_artist=5, ms=360_000)    # 100 nummers × 6 min = 10 uur
    s = settings(target_hours=4, max_per_artist=10)
    hist = {}
    weeks = []
    for w in range(4):
        _, r = build(sp, s, hist, today=TODAY + datetime.timedelta(days=7 * w))
        weeks.append(set(r["uris"]))
        assert not r["short"]
    assert not weeks[0] & weeks[1]                          # 10u materiaal: 2 weken vers
    assert len(weeks[2] & weeks[0]) > len(weeks[2] & weeks[1])   # daarna het oudste eerst


def test_history_bootstraps_from_playlist_added_at():
    sp = world(n_artists=60, per_artist=10)
    s = settings(target_hours=2)
    _, r1 = build(sp, s, {}, today=TODAY)                 # schrijft met added_at = TODAY
    hist = {}                                              # leeg geheugen (bv. eerste HA-run)
    _, r2 = build(sp, s, hist, today=TODAY + datetime.timedelta(days=7))
    assert not set(r1["uris"]) & set(r2["uris"])


def test_seed_rotation_halves_and_alternates():
    sp = FakeSpotify()
    seeds = [sp.add_track(f"S{i}", [sp.find_or_make_artist(f"SA{i}")], ms=180_000) for i in range(40)]
    filler = [sp.add_track(f"F{i}", [sp.find_or_make_artist(f"FA{i}")], ms=180_000)["uri"] for i in range(400)]
    sp.search_results["pop"] = filler
    s = settings(target_hours=1.5, seed_weeks=2)              # 40 seeds × 3 min = 2u
    s["days"]["woensdag"]["seeds"] = [t["id"] for t in seeds]
    seed_uris = {t["uri"] for t in seeds}
    hist = {}
    _, r1 = build(sp, s, hist, today=TODAY)
    _, r2 = build(sp, s, hist, today=TODAY + datetime.timedelta(days=7))
    w1, w2 = set(r1["uris"]) & seed_uris, set(r2["uris"]) & seed_uris
    assert len(w1) == 20 and len(w2) == 20 and not w1 & w2


def test_cross_day_exclusion():
    sp = world(n_artists=60, per_artist=10)
    s = settings(target_hours=2)
    s["days"]["dinsdag"]["searches"] = ["pop"]
    _, r1 = build(sp, s, {}, day="dinsdag", today=TODAY - datetime.timedelta(days=1))
    _, r2 = build(sp, s, {}, day="woensdag")
    assert not set(r1["uris"]) & set(r2["uris"])


# ---------------- nieuwe Dev Mode-apps (beperkte API) ----------------

def test_restricted_api_still_works():
    """Na feb 2026: geen batch, geen popularity, zoeken max 10 per keer."""
    sp = world(n_artists=20, per_artist=5, batch=False, popularity=False, search_limit=10)
    s = settings(target_hours=1)
    _, r = build(sp, s)
    assert not r["short"]
    assert "track" in sp.calls and ("search", 10, 0) in sp.calls


def test_target_owned_by_someone_else_gets_new_playlist():
    sp = world()
    s = settings()
    foreign = sp.make_playlist(owner="iemand-anders")
    s["days"]["woensdag"]["target"] = f"spotify:playlist:{foreign}"
    eng, r = build(sp, s)
    assert eng.settings_changed
    new = s["days"]["woensdag"]["target"].split(":")[-1]
    assert new != foreign and sp.playlists[new]["owner"] == "huis"
    assert sp.playlists[foreign]["items"] == []


def test_remove_from_lists():
    sp = world()
    s = settings()
    eng, r = build(sp, s)
    victim = sp.tracks_db[r["uris"][0]]["artists"][0]["name"]
    n = eng.remove_from_lists(artist=victim)
    pid = s["days"]["woensdag"]["target"].split(":")[-1]
    left = [sp.tracks_db[u]["artists"][0]["name"] for u, _ in sp.playlists[pid]["items"]]
    assert n >= 1 and victim not in left


def test_defaults_are_sane():
    assert set(DEFAULTS["days"]) == set(engine.WEEKDAYS)
    assert len(DEFAULTS["days"]["woensdag"]["seeds"]) == 345
    assert all(engine.track_id(t) for d in DEFAULTS["days"].values() for t in d["seeds"])
    assert "Frenna" in DEFAULTS["block_artists"] and "Madonna" in DEFAULTS["allow_artists"]


# ---------------- covers ----------------

def test_cover_uploaded_once_per_version():
    sp = world()
    s = settings()
    eng, _ = build(sp, s, covers=True)
    covers = [c for c in sp.calls if isinstance(c, tuple) and c[0] == "cover"]
    assert len(covers) == 1 and covers[0][2] < 256 * 1024          # Spotify-limiet base64
    assert eng.settings_changed and s["cover_done"]
    build(sp, s, {}, today=TODAY + datetime.timedelta(days=7), covers=True)
    assert len([c for c in sp.calls if isinstance(c, tuple) and c[0] == "cover"]) == 1


def test_cover_skipped_without_permission_or_when_disabled():
    sp = world()
    build(sp, settings(), covers=False)
    build(sp, settings(covers=False), covers=True)
    build(sp, settings(), dry_run=True, covers=True)
    assert not [c for c in sp.calls if isinstance(c, tuple) and c[0] == "cover"]


def test_cover_403_flags_reauth_but_build_succeeds():
    sp = world()
    sp.cover_status = 403
    eng, r = build(sp, settings(), covers=True)
    assert eng.cover_needs_reauth and r["tracks"] > 0


def test_all_covers_present_and_small():
    for day in engine.WEEKDAYS:
        p = os.path.join(engine.COVERS_DIR, f"{day}.jpg")
        assert os.path.getsize(p) * 4 / 3 < 256 * 1024, day


# ---------------- schriften, gasten, kindermuziek (0.3.0) ----------------

def test_script_filter_is_configurable():
    sp = FakeSpotify()
    jp = sp.add_track("東京", [sp.find_or_make_artist("Q", ["pop"])])["uri"]
    ru = sp.add_track("Привет", [sp.find_or_make_artist("R", ["pop"])])["uri"]
    sp.search_results["pop"] = [jp, ru]
    _, r = build(sp, settings(target_hours=5))
    assert r["uris"] == []
    s = settings(target_hours=5)
    s["block_scripts"] = ["cyrillic"]                    # Japans weer toegestaan
    _, r = build(sp, s)
    assert r["uris"] == [jp]


def test_terms_and_script_checked_on_guest_artists_too():
    sp = FakeSpotify()
    u1 = sp.add_track("Song", [sp.find_or_make_artist("Main", ["pop"]), sp.find_or_make_artist("Yoga Guru")])["uri"]
    u2 = sp.add_track("Song 2", [sp.find_or_make_artist("Main2", ["pop"]), sp.find_or_make_artist("小明")])["uri"]
    sp.search_results["pop"] = [u1, u2]
    _, r = build(sp, settings(target_hours=5))
    assert r["uris"] == []


def test_childrens_music_blocked_by_default():
    sp = FakeSpotify()
    kid = sp.add_track("Hoofd, Schouders, Knie en Teen", [sp.find_or_make_artist("Juf Roos", ["children's music"])])["uri"]
    ok = sp.add_track("Fine", [sp.find_or_make_artist("Goed", ["pop"])])["uri"]
    sp.search_results["pop"] = [kid, ok]
    _, r = build(sp, settings(target_hours=5))
    assert r["uris"] == [ok]
    assert "children's music" in DEFAULTS["block_genres"] and set(DEFAULTS["block_scripts"]) == set(engine.SCRIPTS)
