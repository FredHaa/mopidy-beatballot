# Mopidy-Beat Ballot

A [Mopidy](https://mopidy.com) extension that lets party guests vote on the next
song from their phones.

- **Spotify, Tidal and SoundCloud** playlists are the pool, alone or mixed. Each
  round puts **3 random songs** from all the playlists on the ballot, and guests
  can **search every enabled service and add their own**.
- Voting **locks 20 seconds before the current song ends**. The song with the most
  votes is queued and plays next.
- Losing songs with **2+ votes carry over** to the next round **with their votes**.
  A vote stays on the carried song until that guest votes for something else.
- **Test mode** plays each song for 30 seconds and locks votes after 15.
- Mobile-first web app with live updates, plus a big-screen **host view** with a
  QR code to join.

Guests join at `http://<pi>:6680/beatballot/` with a nickname and the party PIN.
Joining with the host PIN also gives skip, pause, test mode, playlist switching
and removing songs.

## Voting rules

| Situation | What happens |
| --- | --- |
| You vote again | Your vote moves to the new song (one vote per guest) |
| You tap your vote again | Your vote is withdrawn |
| Tie | The song that reached that count first wins |
| Nobody voted | A random playlist pick from the round wins |
| Song loses with ≥ `carry_min_votes` | Carried to the next round, votes kept (unless the host turned carry-over off) |
| Song loses with fewer votes | Dropped; its voters can vote freshly |
| Nothing queued and the music stops | The current leader is locked in and played straight away |

## Music services

| Service | Setup | Notes |
| --- | --- | --- |
| **Tidal** | Nothing in `.env`. On first start, open the host panel (join with the host PIN) and press **Log in to Tidal**, or use the `link.tidal.com` link in `docker compose logs`. | Session is saved in `./data`. Set `TIDAL_QUALITY` (`LOSSLESS` default). |
| **Spotify** | `SPOTIFY_CLIENT_ID`/`SECRET` from <https://mopidy.com/ext/spotify/#authentication>. Needs Premium. | Use playlists you own: Spotify blocks API access to its editorial playlists. Streaming currently fails for some accounts ([librespot#1649](https://github.com/librespot-org/librespot/issues/1649)). |
| **SoundCloud** | `SOUNDCLOUD_AUTH_TOKEN` from <https://mopidy.com/ext/soundcloud/#authentication>. | Playlists are sets: `https://soundcloud.com/<user>/sets/<name>`. |

**No playlists.** Leave `BALLOT_PLAYLISTS` empty for a suggestions-only party:
the ballot holds only songs guests add through search, and the music starts with
the first suggestion. If a round is empty when it locks, the next song added
plays as soon as the current one ends.

**Mixing services.** Enable several and give playlists from each. The random
picks are drawn from all the playlists' songs combined, so a bigger playlist
shows up more often. A song found on two services counts once. Search covers every enabled service and alternates their results.
Every song shows a small badge for its service.

**When a service breaks.** A song that won't play is skipped, and the next one
plays. If 3 songs in a row from one service fail, that service is left out of
the random picks for 10 minutes and the host panel says so. The party carries
on with the other services.

**Tidal login without freezing Mopidy.** Mopidy-Tidal normally logs in on first
use and blocks Mopidy until someone approves it. Beat Ballot runs the device login
itself instead: it shows the link only to the host (whoever opens it connects
their account), saves the session where Mopidy-Tidal looks for it, and keeps
playlists and search away from Tidal until then.

## Run on a Raspberry Pi 4 with Docker

You need 64-bit Raspberry Pi OS (Bookworm or newer), Docker, and a Tidal,
Spotify Premium and/or SoundCloud account.

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out and back in

mkdir beatballot && cd beatballot
curl -O https://raw.githubusercontent.com/FredHaa/mopidy-beatballot/main/compose.yaml
curl -o .env https://raw.githubusercontent.com/FredHaa/mopidy-beatballot/main/.env.example
mkdir data            # must be writable by uid 1000 (the default Pi user)
nano .env             # services, playlists, PINs, audio output
docker compose up -d
docker compose logs -f
```

1. **Services:** set `MUSIC_BACKENDS`, e.g. `tidal` or `spotify,tidal,soundcloud`.
   See [Music services](#music-services) for each one's login.
2. **Playlists:** put share links in `BALLOT_PLAYLISTS`, comma-separated. They can
   also be changed live in the host panel, one per line.
3. **Audio output:** run `aplay -l` on the Pi and set `AUDIO_OUTPUT`, e.g.
   `alsasink device=hw:Headphones` (3.5 mm jack), `alsasink device=hw:vc4hdmi0`
   (HDMI) or `alsasink device=hw:1,0` (USB DAC).
4. **QR code:** set `BALLOT_PUBLIC_URL=http://<pi-ip>:6680/beatballot/` so the host
   view shows the right address. A container can't reliably detect it.
5. Open `http://<pi-ip>:6680/beatballot/#/host` on a TV or laptop and let people
   scan the QR code.

Try `BALLOT_TEST_MODE=true` first. Rounds then take 30 seconds, so you can check
the whole flow quickly. Test mode can also be toggled live from the host panel.

### Building the image

CI (`.github/workflows/ci.yml`) builds `linux/arm64` and `linux/amd64` and pushes
to `ghcr.io/<owner>/beatballot`. To build yourself:

```sh
docker buildx build --platform linux/arm64 -t beatballot .   # cross-build on a PC
docker compose build                                        # or build on the Pi
```

The image is based on `ghcr.io/astral-sh/uv:python3.13-trixie-slim`. uv
installs the locked dependencies (Mopidy-Spotify, Mopidy-Tidal and
Mopidy-SoundCloud are all included), plus the prebuilt `gst-plugin-spotify`
package from [mopidy/gst-plugins-rs-build](https://github.com/mopidy/gst-plugins-rs-build)
and the GStreamer codecs Tidal and SoundCloud streams need (`plugins-bad`, `libav`). PyGObject is compiled in a builder stage, so the runtime image has no
compilers. Cross-building on a PC is much faster than building on the Pi.

Extra Mopidy settings can be mounted at `/etc/mopidy/extra.conf`. See the
commented volume in `compose.yaml`.

## Configuration

`[beatballot]` section (the Docker entrypoint sets these from `BALLOT_*` variables):

| Key | Default | |
| --- | --- | --- |
| `playlists` | | Playlist links or URIs for the random pool, comma or newline separated; empty = guest suggestions only |
| `pin` | `1234` | Guest PIN |
| `admin_pin` | | Host PIN; empty disables host controls |
| `candidates` | `3` | Random songs per round |
| `lock_before_end` | `20` | Seconds before the end of a song that voting locks |
| `carry_over` | `true` | Losing songs with votes carry over (host can toggle live) |
| `carry_min_votes` | `2` | Votes a loser needs to carry over |
| `max_suggestions_per_user` | `1` | Searched songs each guest may add per round |
| `search_schemes` | | URI schemes searched for suggestions; empty = every enabled backend |
| `public_url` | | Join URL shown as a QR code |
| `test_mode` | `false` | Play `test_play_seconds`, lock at `test_lock_at` |
| `test_play_seconds` | `30` | |
| `test_lock_at` | `15` | |

## Development

```sh
# Python. Mopidy needs GStreamer and PyGObject from the system:
sudo apt install python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-plugins-good
uv venv --system-site-packages
uv sync --no-install-package pygobject --no-install-package pycairo
uv run pytest

# Web app
cd web && npm install && npm run build   # outputs to src/mopidy_beatballot/static
```

**UI without Mopidy:** `uv run python dev/demo.py` serves the real web app and
vote engine against a simulated player with a few bot voters. Open
<http://localhost:6680/beatballot/> (PIN `1234`, host PIN `9999`). For hot reload,
run `npm run dev` in `web/` at the same time. Vite proxies the API and WebSocket
to port 6680 (override with `MOPIDY_URL`).

### Layout

```
src/mopidy_beatballot/
  voting.py    vote engine: ballots, ties, carry-over (pure Python)
  backends.py  service names and playlist share links
  tidal_auth.py  Tidal device login without blocking Mopidy
  pool.py      random picks from all playlists, without repeats
  party.py     rounds, lock-in timing, test mode, queueing (Mopidy-free)
  player.py    adapter from Mopidy core to the small Player protocol
  frontend.py  pykka actor + CoreListener; 250 ms ticker drives party.tick()
  web.py       Tornado: PIN join, WebSocket, health, static app
  hub.py       thread-safe broadcast of state to WebSocket clients
web/           Svelte 5 + Vite source
dev/demo.py    simulated party for UI work
```

Timing is position-based. Four times a second the frontend reads the playback
position and locks when `position ≥ end − lock window`. Seeks and pauses are
handled for free. Phones interpolate the countdown locally between server
updates.
