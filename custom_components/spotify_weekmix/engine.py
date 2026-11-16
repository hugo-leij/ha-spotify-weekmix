"""Spotify weekmix: de motor.

Bouwt per weekdag een verse, lange playlist (~18 uur) zonder dubbele nummers,
met een geheugen zodat dezelfde dag niet elke week dezelfde nummers krijgt.

Dit bestand kent GEEN Home Assistant en GEEN globale instellingen: alles komt
binnen via `settings` (een dict, zie defaults.json) en `history`
(song-sleutel -> laatste speeldatum). Zo gebruiken de HA-integratie en het
command-line script (daily_playlists.py) exact dezelfde code.

Waarom het er zo uitziet (de Spotify-API-beperkingen sinds 2024/2026, de
valkuilen per filter): zie CLAUDE.md in de repo.
"""

from __future__ import annotations

import base64
import datetime
import os
import random
import re
from typing import Callable

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

ENGINE_VERSION = "2026-11-16"

# Verhoog dit als de covers opnieuw ontworpen zijn: dan worden ze één keer
# opnieuw op elke playlist gezet. Daarna blijft een cover met rust (ook als de
# gebruiker er zelf een andere op heeft gezet).
COVER_VERSION = 1
COVERS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "covers")

WEEKDAYS = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]

HISTORY_KEEP_DAYS = 180

# Schriften die we niet willen in zoekresultaten (zie CLAUDE.md).
_FOREIGN_SCRIPT = re.compile(
    "["
    "㐀-䶿一-鿿"   # CJK (Chinees/Han)
    "぀-ヿ･-ﾟ"   # Japans (hiragana + katakana, incl. halfwidth)
    "Ѐ-ӿ"                # Cyrillisch
    "ऀ-ॿ"                # Devanagari
    "ঀ-৿"                # Bengaals
    "਀-੿"                # Gurmukhi
    "઀-૿"                # Gujarati
    "଀-୿"                # Oriya
    "஀-௿"                # Tamil
    "ఀ-౿"                # Telugu
    "ಀ-೿"                # Kannada
    "ഀ-ൿ"                # Malayalam
    "฀-๿"                # Thais
    "가-힣ᄀ-ᇿㄱ-ㆎ"   # Koreaans
    "؀-ۿ"                # Arabisch
    "֐-׿"                # Hebreeuws
    "Ͱ-Ͽᾀ-῿"   # Grieks
    "]"
)


def normalize_playlist_id(url_or_id: str) -> str:
    s = (url_or_id or "").strip()
    if "playlist/" in s:
        return s.split("playlist/")[1].split("?")[0]
    if s.startswith("spotify:playlist:"):
        return s.split(":")[-1]
    return s


def track_id(line: str) -> str:
    """Track-ID uit een URL, URI of kale ID ('' als het niets is)."""
    s = (line or "").strip()
    if not s or s.startswith("#"):
        return ""
    s = s.split("?")[0]
    if "track/" in s:
        s = s.split("track/")[1]
    s = s.split("%3a")[-1].split("%3A")[-1].split(":")[-1].split("/")[-1]
    return s if re.fullmatch(r"[0-9A-Za-z]{22}", s) else ""


def song_title(name: str) -> str:
    """Titel genormaliseerd tot 'de song', los van release/versie (zie CLAUDE.md)."""
    title = name.lower().split(" - ")[0]
    title = re.sub(r"[\(\[].*", "", title)
    return title.strip() or name.lower().strip()


def song_key(artist: str, title: str) -> str:
    return f"{artist.lower().strip()}|{song_title(title)}"


def loose_title(key: str) -> str:
    """Titel-deel van een song-sleutel zonder leestekens/spaties ('happy')."""
    return re.sub(r"[^0-9a-z]", "", key.split("|", 1)[-1]) or key


def spread_order(uris: list[str], artist_of: dict[str, str], rnd: random.Random,
                 gap: int) -> list[str]:
    """Willekeurige volgorde met dezelfde artiest zo ver mogelijk uit elkaar.

    Per stap een artiest die de laatste `gap` nummers niet speelde, gewogen naar
    hoeveel nummers die nog over heeft; lukt dat niet, dan de artiest met de
    oudste laatste beurt. Deze volgorde ís de shuffle: Spotify-shuffle hoort uit.
    """
    groups: dict[str, list[str]] = {}
    for u in uris:
        groups.setdefault(artist_of.get(u) or u, []).append(u)
    for g in groups.values():
        rnd.shuffle(g)
    last: dict[str, int] = {}
    out: list[str] = []
    while groups:
        pos = len(out)
        ok = [a for a in groups if pos - last.get(a, -10**9) > gap]
        if ok:
            # Kwadratisch wegen: artiesten met nog veel nummers gaan eerder, anders
            # blijven ze aan het eind samen over en moeten ze wel klonteren.
            a = rnd.choices(ok, weights=[len(groups[x]) ** 2 for x in ok])[0]
        else:
            a = min(groups, key=lambda x: last.get(x, -10**9))
        out.append(groups[a].pop())
        last[a] = pos
        if not groups[a]:
            del groups[a]
    return out


def prune_history(history: dict[str, str], today: datetime.date) -> None:
    cutoff = (today - datetime.timedelta(days=HISTORY_KEEP_DAYS)).isoformat()
    for k in [k for k, v in history.items() if v < cutoff]:
        del history[k]


class DayResult(dict):
    """Samenvatting van één opgebouwde dag (ook bruikbaar als sensor-attributen)."""


class MixEngine:
    """Bouwt dag-playlists. Niet thread-safe; maak er één per run."""

    def __init__(self, sp: Spotify, settings: dict, history: dict[str, str],
                 log: Callable[[str], None] = print, allow_covers: bool = False):
        self.sp = sp
        self.s = settings
        self.g = settings["general"]
        self.history = history
        self.log = log
        self.settings_changed = False          # bv. als een doel-playlist is aangemaakt
        self.allow_covers = allow_covers       # vereist scope ugc-image-upload
        self.cover_needs_reauth = False
        self._genre_cache: dict[str, list[str]] = {}
        self._artist_name_cache: dict[str, str] = {}
        self._single_tracks = False            # batch-endpoints weg (nieuwe Dev Mode-app)
        self._single_artists = False
        self._search_limit = 50
        self._me: str | None = None
        self._refresh_lists()

    # ---------- instellingen ----------
    def _refresh_lists(self) -> None:
        low = lambda xs: frozenset(x.lower().strip() for x in xs if x and x.strip())
        self.block_artists = low(self.s.get("block_artists", []))
        self.allow_artists = low(self.s.get("allow_artists", []))
        self.block_genres = tuple(x.lower() for x in self.s.get("block_genres", []) if x)
        self.block_terms = tuple(x.lower() for x in self.s.get("block_terms", []) if x)
        self.rap_genres = tuple(x.lower() for x in self.s.get("rap_genres", []) if x)
        bt = self.s.get("block_tracks", [])
        self.block_track_ids = {track_id(x) for x in bt if track_id(x)}
        self.block_track_keys = {x.lower().strip() for x in bt if "|" in x}

    # ---------- robuuste API-helpers ----------
    def tracks(self, uris: list[str]) -> list[dict | None]:
        """sp.tracks in blokken van 50; valt terug op één-voor-één als de
        batch-endpoint niet bestaat (Dev Mode-apps van na feb 2026)."""
        out: list[dict | None] = []
        if not self._single_tracks:
            try:
                for i in range(0, len(uris), 50):
                    out += self.sp.tracks(uris[i:i + 50])["tracks"]
                return out
            except SpotifyException as e:
                if e.http_status not in (400, 403, 404, 410):
                    raise
                self.log("batch-tracks niet beschikbaar -> één voor één (traag)")
                self._single_tracks, out = True, []
        for u in uris:
            try:
                out.append(self.sp.track(u))
            except SpotifyException:
                out.append(None)
        return out

    def prewarm_genres(self, artist_ids: list[str]) -> None:
        missing = list({a for a in artist_ids if a and a not in self._genre_cache})

        def store(a):
            if a and a.get("id"):
                self._genre_cache[a["id"]] = a.get("genres") or []
                self._artist_name_cache[a["id"]] = (a.get("name") or "").lower().strip()

        if not self._single_artists:
            try:
                for i in range(0, len(missing), 50):
                    for a in self.sp.artists(missing[i:i + 50])["artists"]:
                        store(a)
                missing = []
            except SpotifyException as e:
                if e.http_status in (400, 403, 404, 410):
                    self._single_artists = True
                missing = [a for a in missing if a not in self._genre_cache]
        for a in missing:
            try:
                store(self.sp.artist(a))
            except SpotifyException:
                pass
            self._genre_cache.setdefault(a, [])

    def playlist_items_dated(self, target: str) -> list[tuple[str, str]]:
        out, res = [], self.sp.playlist_items(normalize_playlist_id(target),
                                              additional_types=["track"], limit=100)
        while res:
            for i in res["items"]:
                t = i.get("track") or i.get("item")
                if t and t.get("uri") and t["uri"].startswith("spotify:track:"):
                    out.append((t["uri"], (i.get("added_at") or "")[:10]))
            res = self.sp.next(res) if res.get("next") else None
        return out

    def me(self) -> str:
        if self._me is None:
            self._me = self.sp.me()["id"]
        return self._me

    # ---------- filters ----------
    def is_blocked_artist(self, names: list[str]) -> bool:
        return any(n.lower().strip() in self.block_artists for n in names)

    def is_blocked_term(self, label: str) -> bool:
        text = label.lower()
        return any(t in text for t in self.block_terms)

    def matches_genre(self, artist_ids: list[str], terms) -> bool:
        joined = " ".join(g for a in artist_ids for g in self._genre_cache.get(a, [])).lower()
        return any(t in joined for t in terms)

    def is_blocked_genre(self, artist_ids: list[str]) -> bool:
        if any(self._artist_name_cache.get(a) in self.allow_artists for a in artist_ids):
            return False
        return self.matches_genre(artist_ids, self.block_genres)

    def popular_enough(self, t: dict) -> bool:
        # 'popularity' bestaat niet meer voor nieuwe Dev Mode-apps -> dan niet filteren.
        pop = t.get("popularity")
        return pop is None or pop >= int(self.g.get("min_popularity", 0))

    @staticmethod
    def _artist_ids(t) -> list[str]:
        return [a["id"] for a in (t.get("artists") or []) if a.get("id")]

    @staticmethod
    def _names(t) -> list[str]:
        return [a["name"] for a in (t.get("artists") or []) if a.get("name")]

    def _is_blocked_track(self, t: dict) -> bool:
        if t.get("id") and t["id"] in self.block_track_ids:
            return True
        names = self._names(t)
        if self.block_track_keys and names:
            if song_key(names[0], t.get("name", "")) in self.block_track_keys:
                return True
        return False

    # ---------- bronnen ----------
    def drop_blocked(self, uris: list[str]) -> list[str]:
        """Bron-playlists: geblokkeerde genres, artiesten en tracks eruit."""
        info = {}
        for t in self.tracks(uris):
            if t and t.get("uri"):
                info[t["uri"]] = t
        self.prewarm_genres([a for t in info.values() for a in self._artist_ids(t)])
        keep = []
        for u in uris:
            t = info.get(u)
            if not t:
                continue
            if (self.is_blocked_genre(self._artist_ids(t)) or self.is_blocked_artist(self._names(t))
                    or self._is_blocked_track(t)):
                continue
            keep.append(u)
        return keep

    def search_track_uris(self, keyword: str, seed: int) -> list[str]:
        candidates = []
        # Altijd vanaf 0 en zo diep als ingesteld. Vroeger schoof het startpunt
        # per dag (0/50/100/150) voor afwisseling; dat sloeg bij termen met weinig
        # resultaten ALLES over. Afwisseling komt nu uit het geheugen (rest_days).
        want = int(self.g.get("search_pages", 19)) * 50
        offset = 0
        while offset < want and offset < 1000:
            try:
                res = self.sp.search(q=keyword, type="track", limit=self._search_limit,
                                     offset=offset, market=self.g.get("market", "NL"))
            except SpotifyException as e:
                if e.http_status == 400 and self._search_limit > 10:
                    self._search_limit = 10            # nieuwe Dev Mode-apps: max 10
                    continue
                break
            items = res["tracks"]["items"]
            if not items:
                break
            for t in items:
                if not t or not t.get("uri"):
                    continue
                if not self.popular_enough(t):
                    continue
                names = self._names(t)
                if self.is_blocked_artist(names) or self._is_blocked_track(t):
                    continue
                label = f"{t['name']} {names[0] if names else ''}"
                if self.is_blocked_term(label) or _FOREIGN_SCRIPT.search(label):
                    continue
                candidates.append((t["uri"], self._artist_ids(t)))
            offset += self._search_limit
        self.prewarm_genres([a for _, ids in candidates for a in ids])
        return [u for u, ids in candidates if not self.is_blocked_genre(ids)]

    @staticmethod
    def _track_year(t) -> int:
        date = (t.get("album") or {}).get("release_date", "")
        return int(date[:4]) if date[:4].isdigit() else 0

    def personal_track_uris(self, day_index: int, min_year: int | None) -> list[str]:
        time_range = ("short_term", "medium_term", "long_term")[day_index % 3]
        tracks = []
        try:
            tracks += self.sp.current_user_top_tracks(limit=50, time_range=time_range)["items"]
        except SpotifyException:
            pass
        try:
            tracks += [i["track"] for i in self.sp.current_user_recently_played(limit=50)["items"]
                       if i.get("track")]
        except SpotifyException:
            pass
        self.prewarm_genres([a for t in tracks for a in self._artist_ids(t)])
        return [t["uri"] for t in tracks
                if t and t.get("uri")
                and self.popular_enough(t)
                and not self.is_blocked_artist(self._names(t))
                and not self.is_blocked_genre(self._artist_ids(t))
                and not self._is_blocked_track(t)
                and (not min_year or self._track_year(t) >= min_year)]

    def track_meta(self, uris: list[str], artist_ids_out: dict) -> dict[str, tuple[str, int]]:
        meta, seen, uniq = {}, set(), []
        for u in uris:
            if u and u not in seen:
                seen.add(u)
                uniq.append(u)
        for t in self.tracks(uniq):
            if t and t.get("uri") and t.get("artists"):
                meta[t["uri"]] = (song_key(t["artists"][0]["name"], t["name"]),
                                  t.get("duration_ms") or 0)
                artist_ids_out[t["uri"]] = self._artist_ids(t)
        return meta

    # ---------- doel-playlist ----------
    def ensure_target(self, day: str) -> str:
        """Geeft een playlist terug die dit account mag beschrijven. Bestaat de
        ingestelde niet of is hij van iemand anders (bv. de standaardinstellingen
        van een ander huis), dan wordt er een nieuwe aangemaakt en onthouden."""
        cfg = self.s["days"][day]
        target = (cfg.get("target") or "").strip()
        if target:
            try:
                pl = self.sp.playlist(normalize_playlist_id(target), fields="owner.id")
                if (pl.get("owner") or {}).get("id") == self.me():
                    return target
            except SpotifyException:
                pass
        name = self.g.get("playlist_name", "{dag}").format(dag=day.capitalize())
        pl = self.sp.current_user_playlist_create(
            name, public=False,
            description=(cfg.get("description", "") + self.g.get("desc_suffix", ""))[:300])
        cfg["target"] = pl["uri"]
        self.settings_changed = True
        self.log(f"[{day}] nieuwe doelplaylist aangemaakt: {pl['uri']}")
        return pl["uri"]

    # ---------- de dag ----------
    def build_day(self, day: str, today: datetime.date | None = None,
                  dry_run: bool = False) -> DayResult:
        today = today or datetime.date.today()
        today_s = today.isoformat()
        cfg = self.s["days"][day]
        g = self.g
        day_index = WEEKDAYS.index(day)
        rnd = random.Random(today.toordinal() + day_index * 1000)
        seed = today.toordinal() + day_index * 1000

        target = self.ensure_target(day) if not dry_run else (cfg.get("target") or "").strip()
        if not dry_run:
            try:
                self.sp.playlist_change_details(
                    normalize_playlist_id(target),
                    name=g.get("playlist_name", "{dag}").format(dag=day.capitalize()),
                    description=(cfg.get("description", "") + g.get("desc_suffix", ""))[:300])
            except SpotifyException:
                pass

        # Andere dagen (uitsluiten) + alles wat in de lijsten staat -> geheugen.
        exclude, played = set(), []
        for other, ocfg in self.s["days"].items():
            t = (ocfg.get("target") or "").strip()
            if not t:
                continue
            try:
                items = self.playlist_items_dated(t)
            except SpotifyException:
                continue
            played += [(u, d) for u, d in items if d and d <= today_s]
            if other != day:
                exclude.update(u for u, _ in items)

        # Sfeer-poel
        mood = []
        for src in cfg.get("sources", []) or []:
            try:
                mood += [u for u, _ in self.playlist_items_dated(src)]
            except SpotifyException as e:
                self.log(f"[{day}] bron {src} niet leesbaar ({e.http_status}) — overgeslagen.")
        mood = self.drop_blocked(mood)
        for kw in cfg.get("searches", []) or []:
            mood += self.search_track_uris(kw, seed)
        rnd.shuffle(mood)

        seeds_pool, seen = [], set()
        for line in cfg.get("seeds", []) or []:
            tid = track_id(line)
            if tid and tid not in seen and tid not in self.block_track_ids:
                seen.add(tid)
                seeds_pool.append(f"spotify:track:{tid}")
        rnd.shuffle(seeds_pool)

        personal = self.personal_track_uris(day_index, cfg.get("min_year"))
        rnd.shuffle(personal)
        pmax = int(g.get("personal_max", 40))
        ordered = personal[:pmax] + mood + personal[pmax:]

        artist_ids: dict[str, list[str]] = {}
        meta = self.track_meta(seeds_pool + ordered + list(exclude) + [u for u, _ in played],
                               artist_ids)
        exclude_keys = {meta[u][0] for u in exclude if u in meta}
        blocked_keys = self.block_track_keys

        hist = self.history
        for u, d in played:
            if u in meta and (meta[u][0] not in hist or hist[meta[u][0]] < d):
                hist[meta[u][0]] = d

        def last_played(u) -> str:
            return hist.get(meta.get(u, ("", 0))[0], "")

        rest_cutoff = (today - datetime.timedelta(days=int(g.get("rest_days", 28)))).isoformat()

        def rested(u) -> bool:
            lp = last_played(u)
            return not lp or lp <= rest_cutoff

        max_rap = cfg.get("max_rap")
        rap_uris = set()
        if max_rap is not None:
            self.prewarm_genres([a for ids in artist_ids.values() for a in ids])
            rap_uris = {u for u, ids in artist_ids.items() if self.matches_genre(ids, self.rap_genres)}

        artist_of = {u: k.split("|", 1)[0] for u, (k, _) in meta.items()}
        seed_set = set(seeds_pool)
        max_per_artist = int(g.get("max_per_artist", 4))
        unique_titles = bool(g.get("unique_titles", True))
        per_artist: dict[str, int] = {}
        target_ms = float(g.get("target_hours", 18)) * 3600 * 1000
        chosen: list[str] = []
        seen_uri, seen_key, seen_title = set(), set(), set()
        state = {"total": 0, "rap": 0}

        def take(uris, respect_exclude, cap_artist=True, fresh_only=False, limit_ms=None):
            stop_at = target_ms if limit_ms is None else min(limit_ms, target_ms)
            for u in uris:
                if state["total"] >= stop_at:
                    break
                if not u or u in seen_uri or u not in meta:
                    continue
                key, dur = meta[u]
                if key in seen_key or key in blocked_keys:
                    continue
                if unique_titles and loose_title(key) in seen_title:
                    continue
                if fresh_only and not rested(u):
                    continue
                if respect_exclude and (u in exclude or key in exclude_keys):
                    continue
                if u in rap_uris and state["rap"] >= max_rap:
                    continue
                art = artist_of.get(u)
                if cap_artist and art and u not in seed_set and per_artist.get(art, 0) >= max_per_artist:
                    continue
                if art:
                    per_artist[art] = per_artist.get(art, 0) + 1
                seen_uri.add(u)
                seen_key.add(key)
                seen_title.add(loose_title(key))
                chosen.append(u)
                state["total"] += dur
                if u in rap_uris:
                    state["rap"] += 1

        seeds_sorted = sorted(seeds_pool, key=last_played)
        seed_ms = sum(meta.get(u, ("", 0))[1] for u in seeds_pool)
        seed_weeks = max(1, int(cfg.get("seed_weeks") or g.get("seed_weeks", 2)))
        take(seeds_sorted, True, limit_ms=seed_ms / seed_weeks)
        take(ordered, True, fresh_only=True)
        oldest_first = sorted(ordered + seeds_sorted, key=last_played)
        if state["total"] < target_ms:
            take(oldest_first, True)
        if state["total"] < target_ms:
            take(oldest_first, False)
        if state["total"] < target_ms:
            take(oldest_first, False, cap_artist=False)

        repeats = sum(1 for u in chosen if not rested(u))
        for u in chosen:
            k = meta[u][0]
            if k not in hist or hist[k] < today_s:
                hist[k] = today_s
        prune_history(hist, today)

        chosen = spread_order(chosen, artist_of, rnd, int(g.get("artist_gap", 20)))
        names = [artist_of.get(u) for u in chosen]
        hours = state["total"] / 3_600_000
        result = DayResult(
            day=day, date=today_s, target=target, tracks=len(chosen), hours=round(hours, 2),
            artists=len(set(names)), max_per_artist=max(per_artist.values(), default=0),
            same_artist_within_5=sum(1 for i, n in enumerate(names) if n and n in names[max(0, i - 5):i]),
            seeds_used=sum(1 for u in chosen if u in seed_set), seeds_total=len(seeds_pool),
            repeats=repeats, short=hours < float(g.get("target_hours", 18)) - 0.5,
            dry_run=dry_run, version=ENGINE_VERSION, uris=chosen,
        )
        self.log(f"[{day}] {len(chosen)} nummers, ~{hours:.1f} uur, {result['artists']} artiesten, "
                 f"max {result['max_per_artist']}/artiest, {result['seeds_used']}/{len(seeds_pool)} seeds, "
                 f"{repeats} herhaald uit de laatste {g.get('rest_days', 28)} dagen (v{ENGINE_VERSION})")
        if result["short"]:
            self.log(f"[{day}] LET OP: te weinig bronmateriaal — voeg bronnen of zoektermen toe.")
        if dry_run or not chosen:
            return result

        self.replace_items(target, chosen)
        self.log(f"[{day}] doelplaylist bijgewerkt.")
        self.ensure_cover(day, target)
        return result

    def ensure_cover(self, day: str, target: str) -> None:
        """Zet de eigen cover van de dag op de playlist, één keer per COVER_VERSION."""
        if not self.allow_covers or not self.g.get("covers", True):
            return
        pid = normalize_playlist_id(target)
        done = self.s.setdefault("cover_done", {})
        if done.get(pid) == COVER_VERSION:
            return
        path = os.path.join(COVERS_DIR, f"{day}.jpg")
        if not os.path.exists(path):
            return
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode()
        try:
            self.sp.playlist_upload_cover_image(pid, data)
        except SpotifyException as e:
            if e.http_status in (401, 403):
                self.cover_needs_reauth = True
            self.log(f"[{day}] cover uploaden mislukt ({e.http_status}): {e.msg}")
            return
        done[pid] = COVER_VERSION
        self.settings_changed = True
        self.log(f"[{day}] cover gezet.")

    def replace_items(self, target: str, uris: list[str]) -> None:
        current = [u for u, _ in self.playlist_items_dated(target)]
        for i in range(0, len(current), 100):
            self.sp.playlist_remove_all_occurrences_of_items(target, current[i:i + 100])
        for i in range(0, len(uris), 100):
            self.sp.playlist_add_items(target, uris[i:i + 100])

    # ---------- blokkeren vanuit HA ----------
    def remove_from_lists(self, *, track_uri: str | None = None,
                          artist: str | None = None) -> int:
        """Haalt een nummer of alle nummers van een artiest uit alle dag-lijsten.
        Geeft het aantal verwijderde tracks terug."""
        removed = 0
        artist_l = (artist or "").lower().strip()
        for cfg in self.s["days"].values():
            target = (cfg.get("target") or "").strip()
            if not target:
                continue
            try:
                uris = [u for u, _ in self.playlist_items_dated(target)]
            except SpotifyException:
                continue
            drop = set()
            if track_uri and track_uri in uris:
                drop.add(track_uri)
            if artist_l:
                for t in self.tracks(uris):
                    if t and any(n.lower().strip() == artist_l for n in self._names(t)):
                        drop.add(t["uri"])
            drop_l = list(drop)
            for i in range(0, len(drop_l), 100):
                self.sp.playlist_remove_all_occurrences_of_items(target, drop_l[i:i + 100])
            removed += len(drop_l)
        return removed

    def check(self) -> list[str]:
        lines = [f"Ingelogd als: {self.sp.me().get('display_name')}"]
        for day in WEEKDAYS:
            cfg = self.s["days"][day]
            bits = []
            for src in cfg.get("sources", []) or []:
                try:
                    n = self.sp.playlist_items(normalize_playlist_id(src), limit=1)["total"]
                    bits.append(f"bron OK ({n})")
                except SpotifyException as e:
                    bits.append(f"bron FOUT {e.http_status}")
            if cfg.get("searches"):
                bits.append(f"{len(cfg['searches'])} zoekterm(en)")
            if cfg.get("seeds"):
                bits.append(f"{len(cfg['seeds'])} seeds")
            lines.append(f"  {day:10s} {'doel OK' if cfg.get('target') else 'GEEN DOEL':10s} "
                         f"{' + '.join(bits) or '-'}")
        return lines
