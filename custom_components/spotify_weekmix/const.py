"""Constanten voor Spotify weekmix."""

DOMAIN = "spotify_weekmix"

OAUTH2_AUTHORIZE = "https://accounts.spotify.com/authorize"
OAUTH2_TOKEN = "https://accounts.spotify.com/api/token"
SCOPES = [
    "playlist-read-private",
    "playlist-modify-private",
    "playlist-modify-public",
    "user-top-read",
    "user-read-recently-played",
    "user-library-read",
    "ugc-image-upload",          # eigen playlist-covers (sinds 0.2.0)
]
COVER_SCOPE = "ugc-image-upload"

STORAGE_VERSION = 1

# Instellingen die alleen voor HA gelden (niet voor de motor).
CONF_AUTO_REFRESH = "auto_refresh"
CONF_REFRESH_TIME = "refresh_time"
CONF_MEDIA_PLAYERS = "media_players"
CONF_SHUFFLE_OFF = "shuffle_off"
CONF_SKIP_ON_BLOCK = "skip_on_block"

HA_DEFAULTS = {
    # Standaard UIT: zolang de oude AppDaemon-job ook draait, zouden ze elkaars
    # lijsten overschrijven. Zet aan zodra AppDaemon is uitgezet.
    CONF_AUTO_REFRESH: False,
    CONF_REFRESH_TIME: "04:00:00",
    CONF_MEDIA_PLAYERS: [],
    CONF_SHUFFLE_OFF: True,
    CONF_SKIP_ON_BLOCK: True,
}

SIGNAL_UPDATED = "spotify_weekmix_updated_{}"

# Interne dag-sleutels (instellingen) zijn Nederlands; naar buiten (entiteiten,
# services) Engels. Wijzig de interne sleutels niet zonder settings-migratie.
DAY_KEYS = {
    "maandag": "monday", "dinsdag": "tuesday", "woensdag": "wednesday",
    "donderdag": "thursday", "vrijdag": "friday", "zaterdag": "saturday", "zondag": "sunday",
}
DAY_FROM_KEY = {v: k for k, v in DAY_KEYS.items()}
