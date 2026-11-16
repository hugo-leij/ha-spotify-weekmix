"""Nep-Spotify voor tests: genoeg API om de motor volledig te draaien, zonder netwerk."""

from __future__ import annotations

import itertools

from spotipy.exceptions import SpotifyException

_ids = (f"{i:022d}" for i in itertools.count(1))


def tid() -> str:
    return next(_ids)


class FakeSpotify:
    def __init__(self, *, batch=True, popularity=True, search_limit=50, me="huis"):
        self.batch, self.popularity, self.search_limit, self._me = batch, popularity, search_limit, me
        self.tracks_db: dict[str, dict] = {}
        self.artists_db: dict[str, dict] = {}
        self.playlists: dict[str, dict] = {}     # id -> {"owner":..., "items":[(uri, added)]}
        self.search_results: dict[str, list[str]] = {}
        self.top: list[str] = []
        self.recent: list[str] = []
        self.calls = []

    # --- opbouw ---
    def artist(self, aid_or_name, genres=None, name=None):
        if aid_or_name in self.artists_db:
            return self.artists_db[aid_or_name]
        aid = "a" + tid()[1:]
        self.artists_db[aid] = {"id": aid, "name": name or aid_or_name, "genres": genres or []}
        return self.artists_db[aid]

    def add_track(self, name, artists, *, ms=200_000, pop=50, year=2020):
        t_id = tid()
        arts = [a if isinstance(a, dict) else self.find_or_make_artist(a) for a in artists]
        t = {"id": t_id, "uri": f"spotify:track:{t_id}", "name": name, "duration_ms": ms,
             "artists": [{"id": a["id"], "name": a["name"]} for a in arts],
             "album": {"release_date": f"{year}-01-01"}}
        if self.popularity:
            t["popularity"] = pop
        self.tracks_db[t["uri"]] = t
        return t

    def find_or_make_artist(self, name, genres=None):
        for a in self.artists_db.values():
            if a["name"] == name:
                return a
        return self.artist(name, genres=genres, name=name)

    def make_playlist(self, owner="huis", uris=(), added="2026-01-01"):
        pid = "p" + tid()[1:]
        self.playlists[pid] = {"owner": owner, "items": [(u, added) for u in uris]}
        return pid

    # --- API ---
    def _t(self, u):
        u = u if u.startswith("spotify:track:") else f"spotify:track:{u}"
        return self.tracks_db.get(u)

    def tracks(self, uris):
        self.calls.append("tracks")
        if not self.batch:
            raise SpotifyException(403, -1, "batch removed")
        assert len(uris) <= 50
        return {"tracks": [self._t(u) for u in uris]}

    def track(self, u):
        self.calls.append("track")
        t = self._t(u)
        if not t:
            raise SpotifyException(404, -1, "not found")
        return t

    def artists(self, ids):
        self.calls.append("artists")
        if not self.batch:
            raise SpotifyException(403, -1, "batch removed")
        return {"artists": [self.artists_db.get(i) for i in ids]}

    def search(self, q, type, limit, offset, market):
        self.calls.append(("search", limit, offset))
        if limit > self.search_limit:
            raise SpotifyException(400, -1, "Invalid limit")
        res = self.search_results.get(q, [])[offset:offset + limit]
        return {"tracks": {"items": [self.tracks_db[u] for u in res]}}

    def me(self):
        return {"id": self._me, "display_name": self._me.capitalize()}

    def playlist(self, pid, fields=None):
        if pid not in self.playlists:
            raise SpotifyException(404, -1, "nope")
        return {"owner": {"id": self.playlists[pid]["owner"]}}

    def playlist_items(self, pid, additional_types=None, limit=100):
        if pid not in self.playlists:
            raise SpotifyException(404, -1, "nope")
        items = [{"track": self.tracks_db[u], "added_at": f"{d}T04:00:00Z"}
                 for u, d in self.playlists[pid]["items"] if u in self.tracks_db]
        return {"items": items, "next": None, "total": len(items)}

    def next(self, res):
        return None

    def playlist_change_details(self, pid, name=None, description=None):
        self.playlists[pid]["name"] = name

    def current_user_playlist_create(self, name, public=True, description=""):
        pid = self.make_playlist(owner=self._me)
        self.playlists[pid]["name"] = name
        return {"id": pid, "uri": f"spotify:playlist:{pid}"}

    def playlist_remove_all_occurrences_of_items(self, target, uris):
        pid = target.split(":")[-1]
        self.playlists[pid]["items"] = [(u, d) for u, d in self.playlists[pid]["items"] if u not in set(uris)]

    def playlist_add_items(self, target, uris):
        pid = target.split(":")[-1]
        self.playlists[pid]["items"] += [(u, self.today) for u in uris]

    today = "2026-11-13"
    cover_status = None          # bv. 403 om een ontbrekend recht na te bootsen

    def playlist_upload_cover_image(self, pid, b64):
        if self.cover_status:
            raise SpotifyException(self.cover_status, -1, "no permission")
        self.calls.append(("cover", pid, len(b64)))

    def current_user_top_tracks(self, limit, time_range):
        return {"items": [self.tracks_db[u] for u in self.top]}

    def current_user_recently_played(self, limit):
        return {"items": [{"track": self.tracks_db[u]} for u in self.recent]}
