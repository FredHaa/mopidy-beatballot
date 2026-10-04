#!/bin/sh
# Render mopidy.conf from environment variables, then start Mopidy.
# Mount extra settings at /etc/mopidy/extra.conf to override anything here.
set -eu

: "${BALLOT_PIN:?Set BALLOT_PIN to the party PIN}"

# Music services to enable, e.g. "spotify", "tidal" or "tidal,soundcloud".
# (Anything after "#" is dropped: plain `docker run --env-file` keeps inline comments.)
backends=$(printf '%s' "${MUSIC_BACKENDS:-spotify}" | sed 's/#.*//' | tr 'A-Z' 'a-z' | tr -d ' ')
for b in $(printf '%s' "$backends" | tr ',' ' '); do
    case "$b" in
        spotify|tidal|soundcloud) ;;
        *) echo "ERROR: unknown backend '$b' in MUSIC_BACKENDS" \
                "(use spotify, tidal and/or soundcloud)" >&2; exit 1 ;;
    esac
done
enabled() { case ",$backends," in *",$1,"*) echo true ;; *) echo false ;; esac; }

if [ "$(enabled spotify)" = true ] && \
   { [ -z "${SPOTIFY_CLIENT_ID:-}" ] || [ -z "${SPOTIFY_CLIENT_SECRET:-}" ]; }; then
    echo "WARNING: SPOTIFY_CLIENT_ID/SPOTIFY_CLIENT_SECRET not set;" \
         "get them from https://mopidy.com/ext/spotify/#authentication" >&2
fi
if [ "$(enabled soundcloud)" = true ] && [ -z "${SOUNDCLOUD_AUTH_TOKEN:-}" ]; then
    echo "WARNING: SOUNDCLOUD_AUTH_TOKEN not set;" \
         "get one from https://mopidy.com/ext/soundcloud/#authentication" >&2
fi

conf=/tmp/mopidy.conf
cat > "$conf" <<CONF
[core]
cache_dir = /var/lib/mopidy/cache
config_dir = /var/lib/mopidy/config
data_dir = /var/lib/mopidy/data

[logging]
verbosity = ${MOPIDY_VERBOSITY:-0}

[audio]
output = ${AUDIO_OUTPUT:-autoaudiosink}
mixer = software
mixer_volume = ${MIXER_VOLUME:-80}

[http]
hostname = 0.0.0.0
port = 6680
default_app = beatballot

[file]
enabled = false

[m3u]
enabled = false

[spotify]
enabled = $(enabled spotify)
client_id = ${SPOTIFY_CLIENT_ID:-}
client_secret = ${SPOTIFY_CLIENT_SECRET:-}
bitrate = ${SPOTIFY_BITRATE:-320}

# Beat Ballot runs the Tidal login itself (link in the host panel and the log)
# and Mopidy-Tidal loads the saved session lazily, so it never blocks.
[tidal]
enabled = $(enabled tidal)
quality = ${TIDAL_QUALITY:-LOSSLESS}
auth_method = OAUTH
login_method = AUTO
lazy = true
login_server_port =

[soundcloud]
enabled = $(enabled soundcloud)
auth_token = ${SOUNDCLOUD_AUTH_TOKEN:-}

[beatballot]
playlists = ${BALLOT_PLAYLISTS:-}
pin = ${BALLOT_PIN}
admin_pin = ${BALLOT_ADMIN_PIN:-}
public_url = ${BALLOT_PUBLIC_URL:-}
test_mode = ${BALLOT_TEST_MODE:-false}
carry_over = ${BALLOT_CARRY_OVER:-true}
lock_before_end = ${BALLOT_LOCK_BEFORE_END:-20}
candidates = ${BALLOT_CANDIDATES:-3}
CONF

configs="$conf"
[ -f /etc/mopidy/extra.conf ] && configs="$configs:/etc/mopidy/extra.conf"

exec mopidy --config "$configs" "$@"
