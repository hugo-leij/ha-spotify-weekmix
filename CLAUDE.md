# CLAUDE.md

Guidance for AI assistants and developers working in this repository.

## Standing instruction: keep the docs current, without asking

Whenever you change behaviour in `custom_components/spotify_weekmix/` (mostly
`engine.py` and `defaults.json`) — a new filter term, a new
genre, a changed default, a new mechanism — **update `README.md` and this file in
the same turn, as part of the change**. This is not a separate task and it is not
something to ask permission for. Do not ask "shall I also update the README?" and
do not report the change as done until the docs match it.

- `README.md` is **English and public** (since 2026-11-15, chosen by the user
  for publishing via HACS): what the integration does, setup, settings,
  entities/services, troubleshooting. Keep house-specific stories (which artist
  was blocked why) out of it — those belong here. The old Dutch house manual is
  in git history (`git show ba82d59:README.md`).
- `CLAUDE.md` is English and written for whoever works on the code next: *why* a
  choice was made, and the traps that were found (which is why almost every
  filter here carries a caveat, e.g. bare `lo-fi`, `italo`, `latin`, `malay`).
- When a filter has collateral damage, name the casualties by artist in both
  files. That is the part that is impossible to reconstruct later.

Committing and pushing are different: those still need to be asked for.

## Name

Public name **Spotify weekmix** — *weekmix* is always written in lowercase in
text (user's preference, 2026-11-16; the images may use capitals) — domain `spotify_weekmix` (renamed from the
working name "Spotify Dagmix"/`spotify_mix` on 2026-11-15, before any install,
so no migration exists or is needed). Repo: `hugo-leij/ha-spotify-weekmix`;
README badges, `manifest.json` URLs and the my.home-assistant links use that
name — update them all if the repo is ever renamed.
Entities use `translation_key`s (en + nl in `translations/`); HA always builds
entity IDs from the **English** translation, so IDs are English
(`sensor.spotify_weekmix_<account>_monday`, `button.…_rebuild_today`) while a
Dutch UI shows "Maandag" / "Ververs lijst van vandaag". Service `day` values are
English (`today`, `all`, `monday`…); the Dutch values (`vandaag`, `alle`,
`maandag`…) are accepted as aliases. Service responses and sensor attributes
use English keys. Still Dutch on purpose: the **internal** weekday keys in
settings/storage (`days.maandag`…, mapped via `const.DAY_KEYS`) — changing
them needs a settings migration — and the default playlist names/descriptions.

## History and publishing

This repo was started fresh on 2026-11-15 from the private development repo
`hugo-leij/spotify-HA` (which still holds the full history: the original
script, the AppDaemon app, the house-specific Dutch README). It was a new repo
on purpose: clean history, public-ready. HACS can only install public repos.
Releases: tag `vX.Y.Z` matching `manifest.json` `version` so HACS shows
versions. `.github/workflows/` runs hassfest, the HACS action
(`ignore: brands` — there is no icon in home-assistant/brands) and pytest.

## What this project does

Generates **seven daily Spotify playlists** (one per weekday) for a home audio
setup (Sonos, driven from Home Assistant). Each playlist is refilled from scratch
with a fresh, mood-appropriate mix that is long enough to play ~18 hours without
ever repeating a song within a day, and — since 2026-11-13 — with a play
history so the same weekday does not get the same songs every week.

Since 2026-11-13 it is a **Home Assistant custom integration** (`spotify_weekmix`,
"Spotify weekmix", HACS-shaped) instead of a script run by AppDaemon:

| File | Role |
|---|---|
| `custom_components/spotify_weekmix/engine.py` | **All selection logic.** No HA imports, no module-level config: everything comes in via a `settings` dict and a `history` dict. Shared by the integration and the CLI. |
| `custom_components/spotify_weekmix/defaults.json` | The default settings (all 7 days incl. 442 seed track IDs, every blocklist). Generated once from the old `daily_playlists.py` constants + `seeds/*.txt`; imported into HA storage on first setup. **The rationale comments that used to sit next to each blocklist entry now live only in this file (CLAUDE.md)** — JSON has no comments. |
| `custom_components/spotify_weekmix/manager.py` | HA glue: `.storage/spotify_weekmix.<entry_id>` (settings + history + last results), runs the engine in the executor, block/unblock, shuffle-off. |
| `__init__.py`, `config_flow.py`, `sensor.py`, `button.py`, `switch.py`, `entity.py` | Standard HA platform code (OAuth via Application Credentials, options flow, services, entities). |
| `daily_playlists.py` | Thin CLI over `engine.py` (loads it by file path so it does not import `homeassistant`). For testing on the NAS. Uses `defaults.json` or a local `settings.json`, history in `history.json`. |
| `tests/` | `test_engine.py` (engine vs. a `FakeSpotify`), `test_integration.py` (real HA test harness), `test_live.py` (real Spotify, dry-run, opt-in). |

## The one thing you must understand first: the Spotify API deprecation

On **2024-11-27** Spotify removed Web API access to a large set of endpoints.
This is the reason the project is shaped the way it is. Do **not** propose
solutions that rely on the removed endpoints — they return HTTP 404/403 and will
not come back.

Removed / unusable (confirmed 404 for this project's app):
- **Spotify-owned playlists** — both algorithmic (`37i9dQZF1E8…`, e.g. daylists,
  radios, mixes) and editorial (`37i9dQZF1DX…`, e.g. "Feel Good Friday",
  "Monday Motivation"). `playlist_items()` on any of these → 404.
- Recommendations (`/recommendations`), Related Artists, Audio Features / Analysis,
  Featured Playlists, Category Playlists, 30s preview URLs in multi-get.

Still working and relied upon here:
- `current_user_top_artists`, `current_user_top_tracks`
- `current_user_recently_played`, `current_user_saved_tracks`
- `artist_top_tracks`
- `search` (track search)
- Reading **regular, user-created** public playlists (`playlist_items`)
- Creating/modifying playlists the authenticated user owns

Consequence: the original design (read Spotify's own weekday radio/editorial
playlists, dedupe, republish) is impossible. We reconstruct each day's mix from
the endpoints that still work.

**Workaround for a specific editorial playlist you want the vibe of:** you can't
read it, but you *can* paste its individual track URLs into a day's **seeds**
(HA: *a day → Seed-nummers*, one per line; stored as track IDs in
`days.<dag>.seeds`). They are curated: priority, and **not** filtered by
popularity/year/blocklist/genre (only `block_tracks` applies). This is how
woensdag is anchored to the user's "'t koffiehuis" / "Werkdag FM" tracks (345
seeds ≈ 19h) and vrijdag to "Summer" (97). Until 2026-11-13 these were
`seeds/woensdag.txt` / `seeds/vrijdag.txt` (comments and all; see git history);
they now only exist in `defaults.json` and HA storage. Note that 345 seeds made
woensdag ~98% identical every week — see seed rotation below. Individual
`sp.tracks()` reads still work even though `playlist_items()` on the editorial
playlist does not.

## How a day's playlist is built (`MixEngine.build_day`)

For a given weekday and date:
1. **Target** — `ensure_target()`: if the configured playlist is not owned by the
   logged-in user (e.g. a friend installed it with Hugo's defaults) or is
   missing, a new private playlist is created and stored back into settings
   (`settings_changed`). Skipped in dry-run.
2. **Exclude set + history bootstrap** — read all seven target playlists *with
   `added_at`*. The other six form the cross-day exclude set; **all seven feed
   the history** (a track in a list was played on the date it was added). That
   is why the history works from the very first run, with no migration step.
3. **Pools** — `sources` (filtered by `drop_blocked`), `searches` (full depth,
   see below), `seeds` (hand-picked IDs from settings), personal
   (`top_tracks` + `recently_played`). Shuffled with a date-seeded RNG.
4. **Selection** (`take()`, every pass enforces within-day uniqueness of song key
   *and* — with `unique_titles` — of the bare title, `block_tracks`, `max_rap`,
   and except where noted `max_per_artist`):
   1. seeds, **least recently played first**, up to `seed duration / seed_weeks`;
   2. the rest (personal first, then mood), **only tracks rested ≥ `rest_days`**
      and not in another day's list;
   3. if short: everything (incl. remaining seeds) **oldest-played first**;
   4. if still short: same, ignoring the cross-day exclude;
   5. if still short: same, ignoring `max_per_artist`.
   A day is never left short to satisfy a preference.
5. **History** — every chosen track is recorded with today's date; entries older
   than 180 days are pruned.
6. **Order** — `spread_order()` (see "Ordering" below).
7. **Write** — remove all current items, add the new ones (100 per request).
   Skipped with `dry_run`. Returns a `DayResult` (tracks, hours, artists,
   max_per_artist, same_artist_within_5, seeds_used, repeats, short, …) that the
   HA sensors expose.

### Why the history exists (measured, 2026-11-13)
"Same songs every wednesday" was reported. Simulating three consecutive weeks
with the old logic (no memory) gave week-over-week overlap of **woensdag 95%,
donderdag 87%, vrijdag 78%, dinsdag 74%, zaterdag 70%, zondag 50%, maandag
27%**. Causes: (a) woensdag's 345 seeds (≈19h) were ~98% of an 18h day, so the
day was the seed list every week; (b) fixed `sources`; (c) search only looked at
300 results starting from a date-dependent offset, so the same top results won.

- **Seed rotation (`seed_weeks`, default 2)** fixes (a). This is a taste
  trade-off: woensdag is the user's favourite *because* of the seeds, and now
  only ~half of them play per week, topped up with `year:2010-2026` searches.
  `seed_weeks: 1` per day restores "all seeds every week" (and the repetition).
- **Full search depth (`search_pages` 6 → 19 = offsets 0…950)** fixes (c):
  dinsdag's candidate pool went from 26h to 53h, donderdag 22h → 54h — ~3 weeks
  of fresh material against `rest_days` 28.
- **Search now always starts at offset 0.** The old `(seed % 4) * 50` start
  offset was a poor man's variety mechanism; for terms with few results it
  skipped *everything* (found by `test_same_release_variants_are_one_song` etc.
  returning 0 tracks). Variety now comes from the history.
- Without enough material the history cannot help — it then degrades to
  "oldest first". If a day's `repeats` stays high, add searches/sources.

**Measured after the change** (`--dry-run` simulation of consecutive weeks with
one shared in-memory history, real Spotify data, 2026-11-13): overlap with the
same weekday one week earlier dropped to **0–6% on every day** (was 27–95%);
all days 18.0h, max 4 per artist, 0 same-artist-within-5. But `repeats`
(tracks played anywhere in the last 28 days) stays high for **dinsdag and
donderdag** from week 2 on (≈270–336 of ~335): their pools are shared with
other days because the *same search terms* are used on several days —
`happy genre:pop` (maandag + dinsdag), `chill genre:pop` (donderdag + zaterdag
+ zondag), `hits genre:dance-pop` (maandag + vrijdag), `dance genre:pop`
(maandag + vrijdag). Those days then alternate between two pools (a song every
other week). The real fix is distinct, measured search terms per day (see the
maandag method) — a taste call left to the user, now doable in the HA UI.
Woensdag/vrijdag "repeats" are mostly seeds by design.

### De-duplication model (important)
"No duplicates" is enforced on a **normalized song key** = `artist|title`, where
`title` is normalized by `_song_title()`: it strips both a `" - …"` suffix
("X - Remaster 2011" → "x") **and** a bracketed suffix ("Don't Cry (Radio
Version)" → "don't cry", "How Old Are You [Vocal Mix]" → "how old are you").
This means the same song in a different release counts as a duplicate.
- The bracket half was added after 7 same-song pairs slipped through in one week
  (e.g. Miko Mission "How Old Are You" twice on the same Friday) — only the
  `" - …"` half existed before.
- Consequence: "Song (feat. X)" and "Song" now collapse to the same key. That is
  intended (same song), but it does mean a feat.-version can displace the plain one.
- Edge case: a title that is *entirely* bracketed ("(I Just) Died In Your Arms")
  would normalize to empty, so `_song_title` falls back to the full lowercased
  name.
- **Within a day:** hard-guaranteed unique — you never hear the same song twice
  in the 18h.
- **Same title, different artist (`unique_titles`, default on):** the day-lists
  had 2× "Wicked Game" (LÖVEE, VELA — covers), 2× "Just the Two of Us", "The Boys
  of Summer" (Don Henley + The Ataris), and 6× different songs titled "Happy" on
  one dinsdag. To a listener a cover *is* a repeat, so the bare title
  (`loose_title`: song title without punctuation/spaces) is unique per day too.
  Collateral: two genuinely different songs that share a generic title ("Desire",
  "Paradise", "Shine") can't both be on one day. Acceptable; plenty of material.
- **Across days:** best effort (pass 1 vs pass 2 above). In practice the current
  sources yield enough material that the whole week is fully unique, but this is
  not guaranteed if sources shrink. Hearing a song on Monday and Thursday is
  considered acceptable since a different list plays each day.

Duration and keys come from `MixEngine.track_meta()`, which batches
`sp.tracks()` (50 URIs per call, falling back to one-by-one, see Dev Mode below)
and returns `uri -> (song_key, duration_ms)`.

## Covers and brand images (0.2.0)

- `covers/<dag>.jpg` (640×640, own design, ~35 KB) are uploaded once per
  playlist per `COVER_VERSION` via `playlist_upload_cover_image`; done-state is
  `settings["cover_done"][playlist_id]`, so a cover the user sets afterwards is
  never overwritten. Bump `COVER_VERSION` to push redesigned covers. The user
  asked to copy Spotify's "Discover Weekly" artwork — declined: Spotify's
  artwork/logo are theirs, especially in a public repo.
- Needs scope `ugc-image-upload` (added in 0.2.0). Old tokens lack it:
  `manager._maybe_reauth_for_covers()` starts a reauth flow **once per HA run**
  and rebuilds continue without covers. If the token has **no** `scope` field
  at all, we can't know — then we just try, and a 401/403 from the upload
  triggers the reauth. (spotipy's refresh response has no `scope`; HA's may.)
- The CLI never uploads covers (`allow_covers=False`): adding the scope to the
  CLI would invalidate the `.cache` token and force an interactive login.
- `brand/` (icon, logo, dark variants, @2x) — HA ≥ 2026.3 serves brand images
  from the integration folder; verified in a local HA 2026.10 (icon shows on
  the integration page). Older HA shows "icon not available".
- All images come from `tools/make_images.py` (Pillow + the OFL font Anton,
  downloaded at run time, git-ignored).
- The day form has *rebuild_now*: saves, then starts `async_rebuild([day])` as a
  background task so the dialog closes immediately.

## Settings (HA options flow / `defaults.json`)

Settings are a dict (schema = `defaults.json`): `general`, `days`, the lists
`block_artists`, `allow_artists`, `block_genres`, `block_terms`, `rap_genres`,
`block_tracks`, and (HA only) `ha`. In HA they live in `.storage` and are edited
via *Configure* (menu: players & schedule / a day / blocklists / general);
`merge_defaults()` adds keys introduced by later versions without touching user
values (a day's `target` is never filled from defaults on merge).

- `general`: `covers` (true), `target_hours` (18), `max_per_artist` (4), `artist_gap` (20),
  `rest_days` (28), `seed_weeks` (2), `unique_titles` (true), `min_popularity`
  (25), `personal_max` (40), `search_pages` (19), `market` ("NL"),
  `playlist_name` ("{dag} – 18 uur muziek"), `desc_suffix`.
- `MIN_POPULARITY` (25) — search results and personal-pool tracks below this
  Spotify popularity score are dropped. This is the main defense against
  royalty-free "production music" filler (tracks like "Corporate Upbeat" /
  "Stay Focused" score ~0), which keyword search otherwise surfaces in bulk.
  If a track has **no** `popularity` field (new Dev Mode apps), it is *not*
  filtered — otherwise every track would be dropped.
- `days.<dag>`: `target`, `description`, `sources` (playlist IDs), `searches`,
  `seeds` (track IDs; the options flow accepts URLs/URIs and normalises with
  `track_id()`, which also understands Sonos' `x-sonos-spotify:spotify%3atrack%3a…`),
  optional `max_rap`, `min_year`, `seed_weeks`. `min_year` drops pre-year tracks
  from search **and** personal pools; searches can also carry `year:A-B`.
- `block_tracks`: entries are either `spotify:track:<id>` or a song key
  `artist|title` (lowercase, `song_title`-normalised). The "block current track"
  button stores both, so other releases of the same song are caught too, and it
  removes the ID from every day's `seeds` (seeds bypass all other filters).
- `ha`: `auto_refresh` (**default false** — see Deployment), `refresh_time`,
  `media_players`, `shuffle_off`, `skip_on_block`.

## Auth model

- **Integration:** standard HA OAuth2 via Application Credentials
  (`application_credentials.py`: Spotify authorize/token URLs). Redirect URI to
  add to the Spotify app: `https://my.home-assistant.io/redirect/oauth`.
  `show_dialog=true` so the user consciously picks the house account. Unique ID =
  Spotify user id; reauth must use the same account (`wrong_account`). A fresh
  `Spotify(auth=access_token)` is created per run after
  `session.async_ensure_token_valid()`.
- **CLI:** `SpotifyOAuth` + `CacheFileHandler` on `.cache` (`open_browser=False`).
  `REDIRECT_URI` `http://127.0.0.1:8888/callback` (Spotify no longer accepts
  `localhost`). The refresh token in `.cache` is portable between machines with
  the same client ID/secret.

## Running / testing

```bash
.venv/bin/python daily_playlists.py --check
.venv/bin/python daily_playlists.py --all --dry-run      # measure, write nothing
```
`--all` with `search_pages` 19 takes several minutes (more search calls, more
genre lookups); the 4-week simulation used for the numbers above took ~1.5h.

Tests need Python ≥3.13 and `pytest-homeassistant-custom-component`; on the
NAS container there is no compiler, so HA 2026.2 (needs `lru-dict` built from
source on 3.13) fails — use **Python 3.14** with the latest harness (HA 2026.10.x):
```bash
uv venv -p 3.14 /tmp/hatest && VIRTUAL_ENV=/tmp/hatest uv pip install pytest-homeassistant-custom-component spotipy
/tmp/hatest/bin/python -m pytest -q                       # 86 tests
SPOTIFY_LIVE_CACHE=<fresh .cache copy> /tmp/hatest/bin/python -m pytest tests/test_live.py -s   # real Spotify, dry-run
```
`test_live.py` must undo the harness' network block (DNS + `socket.connect`) for
itself; and the token in the cache must be fresh, because HA's own token refresh
goes through aiohttp, which the harness also blocks.

Bugs the HA tests caught that would have hit the real UI: `NumberSelector`
rejects `unit_of_measurement=None` (options flow crashed); the scheduled run
used "now" instead of the scheduled time to pick the weekday.

## Deployment

Via HACS (custom repository) or by copying `custom_components/spotify_weekmix`
into `<config>/custom_components/`; HA only loads Python at start, so restart.

**Why `auto_refresh` defaults to off.** Another job (the author's old AppDaemon
script) may still rebuild the same seven playlists at 04:00; both would
overwrite each other. Order: install → test with *Rebuild today* → stop the old
job → switch auto refresh on.

**The stale-copy failure mode (cost two weeks once).** Under AppDaemon, HA ran a
*copy* of the script that silently lagged (78 blocked nederhop tracks on one
maandag, playlists looked fresh). The integration exposes `version` on the
*Status* sensor and in every `DayResult`; compare it with `ENGINE_VERSION` in
`engine.py`. When a blocked artist "comes back", check the version **first**,
then whether the track is a **seed**.

**Checking whether the daily job actually runs:** the day sensors' state is the
last build time; independently, every track in a list shares one `added_at`.

## Resilience

spotipy's `retries` only covers HTTP status codes, not connection/read
timeouts. The CLI wraps `build_day` in `_with_retries()`; in HA a failing day is
reported (`error` in the service response, *Status* = `error`, `last_error`)
and the other days continue. Only one rebuild runs at a time (`asyncio.Lock`).

## Environment gotchas

(Names below like `BLOCK_ARTISTS`, `BLOCK_GENRES`, `ALLOW_ARTISTS`, `RAP_GENRES`,
`BLOCK_TERMS` are the old module constants; they are now the settings lists
`block_artists`, `block_genres`, … with identical semantics, implemented as
`MixEngine.is_blocked_artist` / `is_blocked_genre` / `is_blocked_term`.)

- **Python.** The code uses `int | None` and `list[str]` (≥ 3.10); the HA
  test harness needs 3.13+ (3.14 for current HA). The author develops on a
  Synology NAS without a C compiler, where HA 2026.2 on 3.13 fails to build
  `lru-dict`; 3.14 + the latest harness has wheels.
- **The `.venv` is not portable.** Never copy `.venv` to HA — reinstall
  `spotipy` there instead.
- `spotipy` 2.26.0 has **no `__version__` attribute**; use
  `importlib.metadata.version("spotipy")` if you need it.
- **Search quality**: bare keywords ("morning", "energetic", "focus",
  "motivation") are magnets for yoga/meditation/lo-fi/kids/instrumental/BGM junk.
  The `searches` terms therefore use Spotify search **`genre:` filters**
  (`feel good genre:pop`, `upbeat genre:dance-pop`, `party genre:dance-pop`,
  `chill genre:soul`, …) to keep results on vocal pop/dance/rock. As a second
  net, `search_track_uris` drops any result whose title+artist matches
  `BLOCK_TERMS` (meditation, yoga, sleep, lofi, instrumental, bgm, karaoke,
  plus the slowed/sped-up remix factory: `slowed`, `sped up`, `montagem` — those
  titles often *contain* an innocent word ("MONTAGEM **CHILL** RENICHT - Super
  Slowed") so they match a `chill` search while being hard phonk edits, …)
  or whose title+artist contains non-Latin script via `_has_foreign_script`
  (`_FOREIGN_SCRIPT` regex covers CJK/Han, Japanese kana (hiragana/katakana,
  incl. halfwidth), Cyrillic, Thai, Korean (Hangul+Jamo), Arabic, Hebrew, Greek,
  plus Indic scripts: Devanagari, Bengali, Gurmukhi, Gujarati,
  Oriya, Tamil, Telugu, Kannada, Malayalam) — this is how Chinese/Japanese/Indian/
  Thai/Korean/etc. tracks are filtered. Caveat: romanized/Latin-script titles are not caught by the
  script filter (e.g. BABYMETAL, or romanized Bollywood/Punjabi like "Ishq de
  Fanniyar") — block those by artist via `BLOCK_ARTISTS` (or by title via
  `BLOCK_TERMS`). These two filters (`BLOCK_TERMS` + foreign script) apply to
  **search results only**, not to `sources` playlist tracks (those are user-curated).
- **Unwanted-artist filter (`BLOCK_ARTISTS` / `_is_blocked_artist`)**: a curated
  set of artist names — NL levenslied/volks/schlager (Jan Smit, Rob van Daal,
  Wolter Kroes, …), German schlager (Jürgen Drews, Helene Fischer, …), Bollywood/
  Indian playback singers (Arijit Singh, Manjari, …), German/Mallorca
  "Ballermann" party-schlager (Ikke Hüftgold, Mia Julia, …), rejected
  boybands/groups (BTS, GOT7, 5SOS, …), romanized Japanese acts the script filter
  can't see (ASAYOJI, ONE OK ROCK, Fujii Kaze, …), royalty-free
  production-music channels (Ylecas, …), and novelty bubblegum-eurodance
  (SMiLE.dk — "Japanese Boy"; tagged only `eurodance`/`europop`, so the genre
  filter deliberately lets it through). Matched as an **exact, case-insensitive**
  match against **each** artist name of a track (so collaborations are caught);
  block the distinctive *lead* act of a collab, not a generic collaborator name
  ("Carolina", "Keya") that would risk false positives. Needed because genre
  filters don't exclude these (NL levenslied is also tagged `genre:pop`) and the
  script filter misses romanized titles. Note the Ballermann/schlager stuff is
  genuinely *popular*, so `MIN_POPULARITY` does **not** catch it — hence the
  blocklist. **Ordinary Dutch pop is fine** — only the volkse/levenslied kind is
  blocked. This filter applies to **search results AND the personal pool**
  (`top_tracks`/`recently_played`, since the house account's history can otherwise
  reintroduce them), but **not** to `sources`. To remove more: add the artist name
  to `BLOCK_ARTISTS`.
- **Popularity floor (`MIN_POPULARITY`, 25)**: the single most effective filter
  for the mass of royalty-free production music (generic "Feel Good"/"Upbeat"/
  "Corporate" tracks by no-name upload channels, which score ~0). Applied to
  search results and the personal pool. Real chart pop sits well above it
  (post-cleanup woensdag has a median popularity ~42). Trade-off: it also drops
  genuinely obscure real tracks — acceptable for a background house list.
- **Cyrillic** (`Ѐ-ӿ`, U+0400–U+04FF) was added to `_FOREIGN_SCRIPT` after a
  Ukrainian track slipped through; Latin-script foreign titles still escape it.
- **Tuning a day by measuring, not guessing (the maandag overhaul).** maandag was
  reported as bad; measuring it showed 79 yacht/soft/classic rock, ~32
  christian/worship and 19 gothic/darkwave out of 306. The productive move was to
  run each of the day's `searches` through `search_track_uris` separately and
  tabulate the resulting *artist genres*, yield and median popularity. That named
  the culprits precisely: `upbeat genre:dance-pop` returned 25 tracks that were
  almost entirely christian/worship, and `pop genre:pop-rock` / `hits genre:pop`
  were the yacht-rock tap. Candidate replacements were measured the same way
  before being adopted — `good vibes genre:pop` turns out to return Mexican
  corridos, `energetic genre:pop` yields 21 tracks, `uptempo genre:pop` yields 2.
  Winners: `dance genre:pop` (n=271, median 76), `happy genre:pop` (n=246,
  median 55), `summer genre:pop`, `happy genre:dance-pop`, `hits genre:dance-pop`.
  Result: yacht/soft rock 79 → 8, christian 32 → 0, gothic/darkwave 19 → 0.
  **Do this measurement before changing any day's `searches`.**
- **`sp.search(type="playlist")` still works** — it is not part of the 2024-11
  deprecation, so you can *find* new `sources` rather than only using ones the
  user supplies. Always read the candidate with `playlist_items` first (editorial
  results still 404) and profile it the same way: median popularity, genre mix,
  count of already-blocked artists. maandag gained "Motivation Hits (Werkdag)"
  (median popularity 79) and "Roadtrip 2000-2026" (82) this way.
- **A minimum-followers filter was considered and rejected.** Compilation filler
  like "Zoey Pink – Talk That Talk" (172 followers, `album_type: compilation`)
  clears `MIN_POPULARITY` because *track* popularity is 32. A floor on artist
  followers would catch it — but woensdag, the day the user likes most, is full of
  100–900-follower artists (its hand-picked seeds). Obscurity is not the problem;
  wrong vibe is. Do not add this filter.
- **Genre filter (`BLOCK_GENRES` / `_is_blocked_genre`)**: substring match against
  the **artist genres** (fetched via `sp.artists()`, batched + cached in
  `_genre_cache`, pre-warmed by `_prewarm_genres`). This is the reliable way to
  drop **hardcore/hard-dance** (hardcore, hardstyle, gabber, nightcore,
  frenchcore, happy hardcore, …), **phonk** (substring, so it also covers
  `drift phonk`/`brazilian phonk`; it does not touch ordinary rap/trap), and
  **80s italo-disco / hi-nrg** (`italo disco`, `italo dance`, `hi-nrg`) — the
  *title* never reveals any of this, only the genre does.
  The italo/hi-nrg entries were added because vrijdag's `party/dance
  genre:dance-pop` searches pulled ~30 obscure 80s deep cuts (Ken Laszlo, Miko
  Mission, Spatial Vox, …) into one day — 54 of 320 tracks were in that family,
  none of them from the vrijdag seeds. Two caveats: (a) spell out
  `italo disco`/`italo dance`, **not** bare `italo` — that would also match
  `italo house` (vocal house), same trap as `lo-fi`; (b) `eurodance`/`europop`
  are deliberately **not** blocked, so Vengaboys/Alice Deejay/Aqua survive — but
  a few genuine classics tagged italo/hi-nrg *do* get dropped (Eiffel 65 "Blue",
  Sandra, C.C. Catch, Phil Oakey). Put those in a seed file if you want them
  back — `seeds` bypass the genre filter.
  It also blocks **non-Western-language pop** — Arabic/Turkish (`arab`,
  `egyptian`, `mahraganat`, `shaabi`, `turkish`, `oyun hava`), Indian
  (`bollywood`, `desi`, `punjabi`, `tamil`, `telugu`, `malayalam`, `kannada`,
  `kollywood`/`tollywood`/`mollywood`/`sandalwood`, …) and East/Southeast Asian
  (`k-pop`, `k-ballad`, `k-rock`, `j-pop`, `j-r&b`, `anime`, `kayōkyoku`,
  `v-pop`, `vietnam`, `thai`, `indonesian`, `mandopop`, `cantopop`, `c-pop`).
  This is the **only** filter that catches these: `_has_foreign_script` sees
  nothing once both title and artist are romanized ("Tabadol EL Nazarat",
  "Tera Zikr", most k-pop), and the tracks are popular enough to clear
  `MIN_POPULARITY`. It removed 57 tracks across one week, k-pop being the bulk
  (37). Three tokens are **deliberately left out**, because Spotify tags the
  artist's *origin* rather than the song's language, so they produce false
  positives: bare `malay` (would kill HUGEL "Forever", English house with a
  feature by Malaysian singer Yuna, and HYBS, a Thai band singing English), bare
  `chinese` (`chinese r&b` with English vocals), and `brazilian bass` (Alok,
  Guetta, Vintage Culture — ordinary dance).
  **Reggaeton / urbano latino** is blocked too (`reggaeton`, `urbano latino`,
  `trap latino`, `neoperreo`, `perreo`) — a taste decision the user made, not a
  junk filter. Do **not** widen this to bare `latin` (matches `latin house` —
  English/instrumental house like HUGEL and White Sheep, the same trap as
  `lo-fi`) or to `moombahton` (HUGEL "Forever" carries it *without* reggaeton).
- **Genre-filter exemption (`ALLOW_ARTISTS`)**: a track inherits the genres of
  *all* its artists, so a collab can be killed by the guest's genre. Madonna's
  "Read My Lips" is a duet with Colombian reggaeton artist Feid and dies on
  `reggaeton`, even though Madonna herself has **no genre tags at all**. If any
  artist of a track is in `ALLOW_ARTISTS`, `_is_blocked_genre` returns False.
  Exact case-insensitive name match, like `BLOCK_ARTISTS`; names come from
  `_artist_name_cache`, filled by `_prewarm_genres` from the same `sp.artists()`
  call (no extra requests). Deliberately scoped to the genre filter only — it
  does **not** override `BLOCK_ARTISTS` or the rap cap, so it cannot become a
  general back door. Also covers volks/novelty genres (polka, disco polo, schlager, …) and
  **instrumental-indicating** genres (instrumental, `lo-fi beats`/`lofi hip hop`,
  new age, video game, cinematic, epic music, solo piano, …). Applied to **search
  results, the personal pool, AND `sources`** (via `drop_blocked_genre`, since the
  `sources` are random public playlists that turned out to contain e.g. hardstyle
  in an "Ibiza Chillout" list) — but **not** to `seeds` (those are truly
  hand-picked). Adds one batched `sp.artists()` lookup per search keyword / per
  personal pull / per sources set. Caveats: (a) use `lo-fi beats`/`lofi hip hop`,
  **not** bare `lo-fi` — the latter matches `lo-fi house` (danceable vocal house,
  e.g. Alok) → false positive. (b) true instrumental (vocal vs. vocal-free)
  detection is **impossible** now — the audio-features API is part of the 2024-11
  deprecation — so vocal-free house/EDM tagged only "tropical house" etc. is *not*
  caught; only genre-labelled instrumental is.
- **Rap cap (`max_rap` per day / `RAP_GENRES`)**: rap/hip-hop is **not blocked**
  (the user wants it occasionally), but a day can set `max_rap` (e.g. maandag: 5)
  to stop it dominating. `build_day` tags candidate URIs whose artist genres match
  `RAP_GENRES` (rap, hip hop, trap, drill, grime) — using the artist-id map that
  `track_meta` now also returns — and `take()` skips further rap once the cap is
  hit. Note `genre:funk` was too narrow (2 hits) — verify a genre token returns
  enough results before using it.

  **The cap barely works, and it is worth knowing why.** Measured on one maandag
  list: **153 of 311 tracks (49%) have no artist genre tags at all**, so both
  `RAP_GENRES` and `BLOCK_GENRES` are blind to half the library. Dutch-language
  rap (nederhop) is the worst case — Frenna, Lil Kleine, SFB, Broederliefde,
  Jonna Fraser, Esko, Bokoesam, Josylvio all return `genres=[]`, or at best
  `nederpop`, which is not in `RAP_GENRES`. That maandag list carried ~40
  nederhop tracks while `max_rap` was set to 5: an 8× overshoot the cap could not
  see. Originally two feeders: the account's `recently_played` (someone plays
  nederhop on the house account) and the `genre:pop` searches, since Spotify's
  *search* `genre:` filter classifies differently from the artist-genres endpoint.
  **Now only the searches.** `personal_track_uris` applies `BLOCK_ARTISTS`, so
  once the rappers were blocked the personal pool came back clean — measured 0 of
  82 tracks with a Dutch title. Expect the search side to keep surfacing new
  names, so this list will need occasional additions; it is not a one-off fix.

  Consequence for any future "get X out of my lists" request: check
  `sp.artists()` for the artist **first**. If `genres` is empty, a genre rule is
  useless and `BLOCK_ARTISTS` (a plain name match, no tags needed) is the only
  lever that works.

  **Resolved**: nederhop is now blocked by name in `BLOCK_ARTISTS` (Frenna,
  Ronnie Flex, Lil Kleine, SFB, Broederliefde, Jonna Fraser, Esko, …) — 77 tracks
  across the week, 71 of them on maandag alone. Only the distinctive *lead* acts
  are listed; a collab is caught anyway because `_is_blocked_artist` tests every
  artist on a track. Generic short names (`KM`, `KA`, `Emms`, `Hak`, `Priceless`,
  `Madina`) are deliberately left out — they would sweep up unrelated artists,
  and the lead act already catches those tracks. Verified side effect: Kris Kross
  Amsterdam and GLOWINTHEDARK are **not** blocked themselves, but lose the tracks
  where they feature a blocked rapper ("Adrenaline", "Belazerd") and keep the
  rest. Eight nederhop tracks also had to be deleted from the vrijdag seeds by
  hand — seeds bypass every filter, so a blocklist cannot reach them.

  **Exact-match traps found while building that list** — verify every name against
  `sp.artists()` before adding it, because two near-misses would have destroyed
  innocent artists: `Cité` (NL rap crew) is a different artist from *Nicola Cité*
  (`afro house`), and `HIGH SOCIETY` (NL rap crew) is not *High Step Society*
  (`electro swing`). The exact whole-name match saves you here, but never add a
  partial name. `OYSTER`, `KA`, `Curved`, `KM`, `Emms` are excluded for the same
  reason.

  **How to find the next batch — title matching does not work.** A first sweep
  grepped Dutch stopwords in *track titles* and missed Eves Laurent entirely,
  because his tracks are called "SOFT LEVEN", "IBUPROFEN" and "Streetvibes". The
  method that works: for every artist in the lists whose `genres` is empty (or
  just `nederpop`) and who is not already blocked, pull `artist_top_tracks(country="NL")`
  and test **those** titles for Dutch words — a Dutch-language artist is then
  visible even when the one track in the playlist has an English title. On
  maandag + vrijdag that meant 369 artists to check (~1 API call each, a few
  minutes) and produced 23 candidates, of which 15 were genuinely rap.

  **Deliberately risky entries:** `KM`, `Emms`, `Kevin` are short generic names,
  which the rule above says to avoid. They are in the list anyway because every
  single occurrence in the lists was nederhop (Wagwan, Darling, NO DAYS OFF, WNS,
  Trust, TIJDSVERSPILLING) and without them their solo tracks stay. Verified zero
  collateral at the time of adding. If an unrelated artist called "Kevin" or "KM"
  ever vanishes, this is why.

  **Scope boundary — do not "helpfully" widen this.** The request was Dutch *rap*.
  Dutch-language R&B/pop is deliberately left in: Yade Lauren, Cristian D, Isabèl
  Usher, plus ordinary Dutch pop (Danny Vera, Ilse DeLange, Krezip, Kensington),
  Dutch R&B (Denisha, Kaya Imani, Sigourney K) and Dutch feest/novelty
  (Bankzitters, JOB, Maxime & Sophie, and the YouTuber tracks by Rutger Vink /
  Thomas van Grinsven). A Dutch title is not by itself grounds for blocking.
  One find worth raising with the user rather than acting on: **`Yaëlle` is
  children's music** ("Wij Zijn Groep 3", "Dans Maar Mee", "Miljoenen Dromen") and
  slipped past `BLOCK_TERMS`, which only has English kid-music terms
  (`kinderlied`, `children's`, `kids music`) — a Dutch-language kids act matches
  none of them.

  **Known inconsistent state (open question with the user):** `Flaire` is in
  `BLOCK_ARTISTS` as a borderline call (`nederpop`-tagged but Dutch-language
  urban — "Boefie Energy", "Seks", a collab with Def), yet the track
  "Door Het Oog Van De Nacht" is also in the vrijdag seeds, which bypasses the
  blocklist. So it is banned on six days and allowed on vrijdag. The user picked
  that seed by hand, which argues for removing the name from `BLOCK_ARTISTS`
  rather than deleting the seed. Awaiting their call — do not silently pick one.

  Also still unresolved: `K7` — "I'll Make You Feel Good - Extended Version",
  genre `freestyle` (1993 US hip-house, not Dutch rap). Reported as unwanted but
  out of scope for the nederhop block, so it is untouched.

## Ordering, artist cap and why Spotify shuffle must be OFF

The user reported that "Spotify shuffle is not a real shuffle". Measured on the
live lists (2026-11-13) before changing anything: with a plain `rnd.shuffle`,
zondag had Bryson Tiller 21× and 12 cases of the same artist within 5 tracks;
donderdag had Mecdoux 13×; vrijdag INNA/Madonna/Vengaboys 10× each. Tracing
origin showed **seeds were almost never the cause** — the repeats come from
`sources` (Mecdoux, a balladeer, Charlie Dée, TWOPILOTS) and search/personal
(Bryson Tiller, INNA, Madonna).

Two mechanisms:
- **`max_per_artist` (4)** in `take()`, keyed on the *primary* artist (the part
  of the song key before `|`). Seed tracks count toward the cap but are never
  refused — they are hand-picked. A third `take` pass without the cap exists so
  a day is never short; in the 2026-11-13 dry-run no day needed it (all 7 hit
  18h with max 4).
- **`spread_order()`** replaces the final shuffle: at each step pick a random
  artist that has not played in the last `artist_gap` (20) tracks, weighted by
  the **square** of how many tracks it has left (linear weighting still let heavy
  artists pile up at the end, where they *must* cluster; a 200-seed stress test
  with gap 5 showed occasional clusters, gap 20 and quadratic weights showed
  none). If none qualifies, take the artist with the oldest last turn. Result:
  0 same-artist-within-5 on all seven days.

The playlist order *is* the shuffle, so playback must have shuffle **off**.
Spotify's shuffle re-randomises on every playback start (so after each Sonos
restart you hear a similar "favourite" opening), and **Smart Shuffle injects
recommended tracks that bypass every filter in this script**. The integration
therefore calls `media_player.shuffle_set shuffle=false` after each (non-dry)
rebuild on `ha.media_players` (option *shuffle_off*, default on).

Dry-run (`build_day(..., dry_run=True)`, CLI `--dry-run`, service
`rebuild` with `dry_run: true`) runs everything except writes (also skips
`ensure_target`/`playlist_change_details`) and does not persist history. Use it
to measure before committing a tuning change.

## Spotify Development Mode restrictions (Feb/Mar 2026) — this app is grandfathered

Since 2026-02-11 (new apps) / 2026-03-09 (existing apps) Spotify restricts
Development Mode apps: owner needs **Premium**, max **5 users** per app, batch
`GET /tracks` and `GET /artists` removed, `popularity` removed from tracks and
artists, search `limit` max 10, artist top-tracks removed, and playlist items
only readable for playlists the user owns/collaborates on. Source: Spotify's
"February 2026 Web API Dev Mode Changes – Migration Guide".

Probed on 2026-11-13 with the Saints app: **none of this applies yet** — batch
tracks/artists, `popularity`, search limit 50, `artist_top_tracks` and reading
third-party `sources` all still work. That can change without notice, and this
script leans on exactly those things (`MIN_POPULARITY`, `sources`, batching).
Consequences:
- **Never recreate the Spotify app** / client ID; a new one gets the restricted API.
- Friends installing the integration run on *their* new apps. The engine
  degrades instead of breaking: batch `tracks`/`artists` → per-item calls on
  400/403/404/410 (slow: ~1 call per track); missing `popularity` → not
  filtered; search 400 on `limit=50` → `limit=10` with more pages; unreadable
  `sources` → skipped with a log line; foreign/missing `target` → a new
  playlist is created. Covered by `test_restricted_api_still_works`, but never
  run against a real restricted app.
- spotipy 2.26 already uses the new `/playlists/{id}/items` endpoints and
  `POST /me/playlists` (`current_user_playlist_create`).

## Working on a Synology share: `@eaDir` breaks git

When a working copy is copied onto a Synology share from a Mac, Synology
creates `@eaDir/*@SynoEAStream` (macOS extended attributes) in every directory
— **including inside `.git`**. `.git/refs/@eaDir/heads@SynoEAStream` makes
`git fetch` fail with "bad object refs/@eaDir/…". Fix:
`find .git -type d -name '@eaDir' -prune -exec rm -rf {} +` (only inside
`.git`; these are metadata). `@eaDir/` is in `.gitignore`. Such a copy may also
set every file to 755: `git config core.fileMode false`.

## Security note

Client credentials live in a git-ignored `.env` (CLI) or in HA's Application
Credentials (integration), never in source. `.cache`, `history.json` and
`settings.json` are git-ignored too.
