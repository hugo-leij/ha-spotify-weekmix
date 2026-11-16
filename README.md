<p align="center"><img src="custom_components/spotify_weekmix/brand/logo@2x.png" alt="weekmix" height="96"></p>

# Spotify weekmix for Home Assistant

[![HACS Custom][hacs-badge]][hacs]
[![GitHub Release][release-badge]][releases]
[![Validate][validate-badge]][validate]
[![Tests][tests-badge]][tests]
[![Home Assistant][ha-badge]][ha]
[![License][license-badge]](LICENSE)

**Seven fresh Spotify playlists, one for every day of the week — each about 18
hours long, no song twice in a day, and not the same songs every week.**

Built for whole-house audio (Sonos or any other `media_player`) that plays all
day. Each morning the playlist for today is rebuilt from scratch in the mood you
set for that day, from playlists, searches and hand-picked tracks — and it
remembers what played recently, so Wednesday doesn't sound like last Wednesday.

[![Open your Home Assistant instance and open this repository in HACS.][my-hacs-badge]][my-hacs]
[![Open your Home Assistant instance and start setting up Spotify weekmix.][my-flow-badge]][my-flow]

---

## Features

- **No repeats within a day.** Hard guarantee on *artist + title*, so a remaster,
  radio edit or live version counts as the same song. Optionally also no two
  songs with the same title (covers, five different songs called "Happy").
- **No repeats week over week.** Every track gets a rest period (default 28
  days) before it may come back on any day. If there isn't enough fresh
  material, the tracks that played *longest ago* are used first — a day is
  never left short.
- **Hand-picked seeds that rotate.** Paste your favourite tracks per day; they
  get priority but rotate (default: half of them each week, least recently
  played first) so a favourite list doesn't turn into the same day every week.
- **A shuffle that doesn't clump.** Tracks are ordered so the same artist is at
  least ~20 tracks apart, and at most 4 tracks per artist per day. Spotify's own
  shuffle is turned off after each refresh (it re-randomises on every start,
  and Smart Shuffle injects tracks that bypass your filters).
- **"Never this again" buttons.** Block the artist or track that is playing
  right now: it is added to the blocklist, removed from all seven playlists,
  and the player skips to the next track.
- **Filters** for blocked artists, tracks, genres and words in titles, a
  popularity floor against royalty-free filler, a per-script filter (Chinese,
  Japanese, Korean, Cyrillic, Arabic, Hebrew, Greek, Thai, Indian scripts — each
  can be switched off), a minimum release year and a cap on rap tracks per day.
- **Everything configurable in the UI**: per day (target playlist, source
  playlists, search terms, seeds, minimum year, rap cap), blocklists, players,
  schedule and general settings.
- **Recently played sensor.** The last 10 Spotify tracks on your players, with
  everything needed to block (or unblock) them from a card of your own design —
  taken from the players in Home Assistant, so no extra Spotify API calls.
- **A cover per day.** Each playlist gets its own weekmix cover (once; a
  cover you set yourself afterwards is left alone).
- **Sensors** per day (last refresh, tracks, hours, artists, seeds used,
  repeats) and a status sensor with the running version and the last error.

## Why not just use Spotify's own mixes?

Since 27 November 2024 the Spotify Web API no longer exposes Spotify-owned
playlists (Daily Mixes, daylists, radios, editorial lists like "Feel Good
Friday"), recommendations, related artists or audio features. weekmix builds
each day from what still works: regular user playlists, search, your own top
and recently played tracks, and individual tracks you pick.

## Requirements

- Home Assistant **2025.1** or newer.
- A Spotify account for the house (playlists are created and rewritten on this
  account).
- A Spotify app from the [Spotify developer dashboard](https://developer.spotify.com/dashboard).

> [!IMPORTANT]
> **Spotify's 2026 Development Mode rules.** Apps created after 11 February 2026
> need a **Premium** owner, allow **max. 5 users**, and get a reduced API (no
> track popularity, no batch lookups, max. 10 search results per request, and
> only playlists you own or collaborate on are readable). weekmix still works
> on such an app, but without the popularity filter and without *source
> playlists*, and slower. **If you already have an older Spotify app, reuse it.**

## Installation

### HACS (recommended)

1. Click the *Open in HACS* button above, or in HACS go to **⋮ → Custom
   repositories** and add `https://github.com/hugo-leij/ha-spotify-weekmix` as type
   **Integration**.
2. Download **Spotify weekmix** and restart Home Assistant.

### Manual

Copy `custom_components/spotify_weekmix` into `<config>/custom_components/`
and restart Home Assistant.

## Setup

1. In the [Spotify developer dashboard](https://developer.spotify.com/dashboard),
   open your app → **Settings** → **Redirect URIs** and add
   ```
   https://my.home-assistant.io/redirect/oauth
   ```
2. In Home Assistant: **Settings → Devices & services → Add integration →
   Spotify weekmix** (or use the *start setup* button above).
3. Enter the app's **Client ID** and **Client Secret**, then log in with the
   house account and click *Agree*.
4. Open the integration's **Configure** menu, pick your players under
   **Players & schedule**, and switch on **Refresh automatically every day**.

> [!NOTE]
> Automatic refresh is **off** after installation, so it can't fight with an
> existing script that rebuilds the same playlists. Press **Rebuild today's
> playlist** once to check the result first.

Days that have no target playlist yet (or one owned by another account) get a
new private playlist named after the day, e.g. *Maandag – 18 uur muziek*.

## Configuration

All settings live under the integration's **Configure** menu.

| Menu | Settings |
|---|---|
| **Players & schedule** | Players (the first one is used by the block buttons), daily refresh on/off and time, turn shuffle off after refreshing, skip after blocking |
| **Configure a day** | Target playlist, description, source playlists, search terms, seed tracks, no tracks before year, max. rap tracks, seed rotation — and *Rebuild this day's playlist now* to apply the change immediately |
| **Blocklists** | Scripts to block, blocked artists, blocked tracks, exceptions to the genre filter, blocked genres, blocked words, genres counted as rap — one per line |
| **General** | Length per day (18 h), max. per artist (4), artist gap (20), track rest (28 days), seed rotation (2 weeks), no duplicate titles, cover per day, minimum popularity (25), own top/recent tracks per day (40), search depth (19 pages), market (NL), playlist name |

**Choosing search terms.** Bare words like *focus* or *morning* pull in yoga,
lo-fi and background music. Use Spotify's genre filter, e.g. `happy genre:pop`,
`chill genre:house`, optionally with `year:2010-2026`. Days that share search
terms share their pool of tracks, so give each day its own terms if you want
fewer repeats.

**Filters and their traps.** Genre and word filters match *part of the text*:
`lo-fi` also matches `lo-fi house`, `italo` matches `italo house`, `latin`
matches `latin house`. Prefer specific terms (`lo-fi beats`, `italo disco`).
Artist names must match exactly; collaborations are caught on any artist.
Words and scripts are checked against the title and **all** artists of a track,
so a guest artist counts too. Seeds bypass every filter except *blocked tracks*.

**Children's music** is recognised by its genre: Spotify tags kids' acts
(Juf Roos, Kinderen voor Kinderen, Dirk Scheele, Nijntje, Studio 100, CoComelon,
Pinkfong, …) as `children's music` and often `lullaby`; both are in the default
genre blocklist. Kids' songs by artists *without* that tag only get caught by
words in the title (`kinderlied`, `children's`, `nursery`, …) or by blocking the
artist.

### Default settings

The integration ships with the author's own setup as defaults: market NL, a mood per day (energetic Monday → chill Sunday), two seed
lists, and blocklists aimed at a Dutch household (schlager/levenslied, Dutch
rap, k-pop, hardstyle, phonk, reggaeton, kids' and Christmas music, …). Change
them freely — your changes are stored in Home Assistant and are never
overwritten by updates. When a new version adds items to a default list (for
example `children's music` in 0.3.0), only those new items are added to your
list, once.

### Covers

![Covers](docs/covers.jpg)

weekmix uploads its own cover to each day's playlist once. This needs the
Spotify permission `ugc-image-upload`. Logins made with version 0.1.x don't
have it: Home Assistant then shows **Re-authenticate** — log in again with the
same account. Until then the playlists are still rebuilt, just without a
cover. Turn covers off under *General* if you prefer your own images.

## Entities

Entity IDs are always English; names follow your Home Assistant language
(English and Dutch included). `<account>` is the Spotify display name, e.g.
`sensor.spotify_weekmix_saints_monday`.

| Entity | Description |
|---|---|
| `button.spotify_weekmix_<account>_rebuild_today` | Rebuild today's playlist now |
| `button.spotify_weekmix_<account>_never_this_artist_again` | Block the artist playing on the first player |
| `button.spotify_weekmix_<account>_never_this_track_again` | Block the track playing on the first player |
| `switch.spotify_weekmix_<account>_automatic_daily_refresh` | Daily automatic refresh |
| `sensor.spotify_weekmix_<account>_monday` … `_sunday` | Time of the last refresh; attributes `tracks`, `hours`, `artists`, `seeds_used`, `repeats`, `playlist_uri`, `playlist_url`, … |
| `sensor.spotify_weekmix_<account>_recently_played` | Last track played (`artist – title`); attribute `tracks`: the last 10, newest first |
| `sensor.spotify_weekmix_<account>_status` | `ok`, `running` or `error`; attributes `last_error`, `version`, `blocked_artists`, `tracks_in_history`, … |

## Services

| Service | Fields |
|---|---|
| `spotify_weekmix.rebuild` | `day`: `today` (default), `all`, or `monday` … `sunday` · `dry_run`: compute only |
| `spotify_weekmix.block_artist` | `artist` (empty = now playing) · `entity_id` (player) |
| `spotify_weekmix.block_track` | `track` (Spotify link/URI; empty = now playing) · `entity_id` |
| `spotify_weekmix.unblock_track` | `track` (Spotify link/URI) |
| `spotify_weekmix.unblock_artist` | `artist` |

`block_track` and `block_artist` return immediately: the blocklist is saved,
sensors update and the player skips right away; removing the track(s) from all
seven playlists happens in the background (~15 s of Spotify API calls). A
failure there shows up on the status sensor.

All services return a response, e.g. the result of a rebuild:

```yaml
action: spotify_weekmix.rebuild
data:
  day: today
  dry_run: true
response_variable: result
```

Example: start today's playlist in the morning, with shuffle off.

```yaml
automation:
  - alias: Morning music
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: media_player.shuffle_set
        target: { entity_id: media_player.living_room }
        data: { shuffle: false }
      - action: media_player.play_media
        target: { entity_id: media_player.living_room }
        data:
          media_content_type: playlist
          media_content_id: >-
            {{ state_attr('sensor.spotify_weekmix_saints_' ~ ['monday','tuesday','wednesday',
               'thursday','friday','saturday','sunday'][now().weekday()], 'playlist_uri') }}
```

## Recently played

`sensor.spotify_weekmix_<account>_recently_played` follows the players selected
under *Players & schedule*: every new Spotify track that starts playing is added
at the top (radio/TV and grouped speakers playing the same track are ignored).
It reads the players' state in Home Assistant — no Spotify API calls — and
survives restarts. Each item in the `tracks` attribute looks like:

```yaml
track_id: 4uLU6hMCjMI75M1A2tKUQC
uri: spotify:track:4uLU6hMCjMI75M1A2tKUQC
url: https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC
title: Blinding Lights
artist: The Weeknd
album: After Hours
image: /api/media_player_proxy/...
player: media_player.living_room
played_at: "2026-11-16T09:41:03+00:00"
blocked: false          # track is on the blocklist
artist_blocked: false   # artist is on the blocklist
```

Build any card you like on top of it. An example with only built-in cards: a
script that blocks item *n*, and a card that lists the tracks.

```yaml
script:
  weekmix_block_recent:
    alias: Block a recently played track
    fields:
      index: { selector: { number: { min: 0, max: 9 } } }
      what: { selector: { select: { options: [track, artist] } } }
    sequence:
      - variables:
          item: "{{ state_attr('sensor.spotify_weekmix_saints_recently_played', 'tracks')[index | int] }}"
      - if: "{{ what == 'artist' }}"
        then:
          - action: spotify_weekmix.block_artist
            data: { artist: "{{ item.artist.split(',')[0] }}" }
        else:
          - action: spotify_weekmix.block_track
            data: { track: "{{ item.uri }}" }
```

```yaml
type: markdown
title: Recently played
content: >
  {% for t in state_attr('sensor.spotify_weekmix_saints_recently_played', 'tracks') or [] %}
  {{ loop.index0 }}. {{ '~~' if t.blocked or t.artist_blocked }}**{{ t.title }}** – {{ t.artist }}{{ '~~' if t.blocked or t.artist_blocked }}
  {% endfor %}
```

Add buttons (e.g. a *Button* card with `tap_action: perform-action`,
`perform_action: script.weekmix_block_recent`, `data: {index: 1, what: track}`)
or use a custom card such as Mushroom or button-card for a list with a button
per row.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Same songs every week | Check the day sensor's `date`: is the daily refresh on? If the date is current but `repeats` is high, the day doesn't have enough material — add search terms or a source playlist. |
| Shuffle doesn't feel random | Spotify shuffle is on. Pick your players under *Players & schedule*; weekmix turns it off after each refresh. |
| `INVALID_CLIENT: Invalid redirect URI` | Add `https://my.home-assistant.io/redirect/oauth` to the app's Redirect URIs. |
| `403 – user not registered` | Add the account under *User Management* in the Spotify app (Development Mode). |
| `404` on a source playlist | It's a Spotify-owned playlist (`37i9dQ…`); those can't be read. Use a regular playlist, search terms or seeds. |
| A blocked artist comes back | Is the track a *seed*? Seeds bypass the artist and genre filters; *Never this track again* removes it from the seeds. |
| "Re-authenticate" after updating | Version 0.2.0 needs one extra Spotify permission for covers. Log in again with the same account. |
| Block buttons unavailable | No player selected under *Players & schedule*. |
| Status sensor shows `error` | See the `last_error` attribute and the log (search for `spotify_weekmix`). |

## Development

The selection logic is in
[`custom_components/spotify_weekmix/engine.py`](custom_components/spotify_weekmix/engine.py)
and has no Home Assistant dependency. `daily_playlists.py` is a small CLI around
it for testing with the default settings:

```bash
python -m venv .venv && .venv/bin/pip install spotipy
cp .env.example .env              # SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET
.venv/bin/python daily_playlists.py --check
.venv/bin/python daily_playlists.py --all --dry-run   # computes everything, writes nothing
```

Images (covers and brand icon) are generated by `uv run --script tools/make_images.py`.

Tests (Python 3.13+):

```bash
pip install pytest-homeassistant-custom-component spotipy
pytest
```

`tests/test_engine.py` runs the engine against a fake Spotify,
`tests/test_integration.py` runs the integration in the Home Assistant test
harness, and `tests/test_live.py` does a dry run against the real API when
`SPOTIFY_LIVE_CACHE` points to a spotipy token cache.

## License

[MIT](LICENSE). Not affiliated with or endorsed by Spotify.

[hacs]: https://github.com/hacs/integration
[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge
[releases]: https://github.com/hugo-leij/ha-spotify-weekmix/releases
[release-badge]: https://img.shields.io/github/v/release/hugo-leij/ha-spotify-weekmix?style=for-the-badge
[validate]: https://github.com/hugo-leij/ha-spotify-weekmix/actions/workflows/validate.yml
[validate-badge]: https://img.shields.io/github/actions/workflow/status/hugo-leij/ha-spotify-weekmix/validate.yml?style=for-the-badge&label=validate
[tests]: https://github.com/hugo-leij/ha-spotify-weekmix/actions/workflows/tests.yml
[tests-badge]: https://img.shields.io/github/actions/workflow/status/hugo-leij/ha-spotify-weekmix/tests.yml?style=for-the-badge&label=tests
[ha]: https://www.home-assistant.io/
[ha-badge]: https://img.shields.io/badge/Home%20Assistant-2025.1%2B-03a9f4?style=for-the-badge&logo=homeassistant
[license-badge]: https://img.shields.io/github/license/hugo-leij/ha-spotify-weekmix?style=for-the-badge
[my-hacs]: https://my.home-assistant.io/redirect/hacs_repository/?owner=hugo-leij&repository=ha-spotify-weekmix&category=integration
[my-hacs-badge]: https://my.home-assistant.io/badges/hacs_repository.svg
[my-flow]: https://my.home-assistant.io/redirect/config_flow_start/?domain=spotify_weekmix
[my-flow-badge]: https://my.home-assistant.io/badges/config_flow_start.svg
