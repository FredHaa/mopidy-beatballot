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
- **Hub and players:** one server can host many parties, each playing on its own
  small player (a Raspberry Pi with speakers) anywhere with internet.

Guests join with a nickname and the party PIN. Joining with the host PIN also
gives skip, pause, test mode, playlist switching and removing songs.

## Three ways to run it

| Mode | What it does | Typical setup |
| --- | --- | --- |
| `standalone` (default) | One party; voting and music on the same machine | A Pi with speakers at home |
| `hub` | Many parties; voting, search and logins on a server; plays nothing itself | A server behind your domain |
| `player` | Plays what its hub sends | A Pi or PC with speakers at each venue |

Choose with `BALLOT_MODE`. The same Docker image does all three.

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

## Hub and players

The hub hosts parties at `https://<hub>/beatballot/r/<party>/`. Each party has its
own name, guest and host PINs, QR code and ballot, and plays on one paired player.
Players connect *out* to the hub over a WebSocket, so they work behind any router
without port forwarding.

**No accounts on the players.** The hub logs in to Tidal/SoundCloud once. For each
song it resolves a short-lived stream URL (Tidal's are valid for about an hour)
and sends only that to the party's player, which plays it through its own Mopidy.
Spotify can't work this way (its plugin streams through the account itself), so a
hub leaves Spotify songs out of search.

**Set up the hub** (`compose.yaml` on your server):

```sh
BALLOT_MODE=hub
BALLOT_HUB_PIN=…                 # the hub owner's PIN
MUSIC_BACKENDS=tidal             # and/or soundcloud
BALLOT_PUBLIC_URL=https://www.example.party/beatballot/
# Optional: BALLOT_PIN/BALLOT_ADMIN_PIN/BALLOT_PARTY_NAME create a first party
```

Open `https://<hub>/beatballot/#/hub` and log in with the hub PIN to:
- connect Tidal (one-time device login),
- create parties (PINs are random unless you choose them),
- **pair a player**: you get a one-time code (valid 15 minutes) and a ready
  `docker run` command,
- see each party's player (online or offline) and what's playing, rename parties,
  change PINs (signs that party's guests out), unpair or delete.

**Set up a player** (on the Pi, with the code from the hub page):

```sh
docker run -d --name beatballot-player --restart unless-stopped \
  --device /dev/snd --group-add audio -v beatballot-player:/var/lib/mopidy \
  -e BALLOT_MODE=player -e BALLOT_HUB_URL=https://www.example.party \
  -e BALLOT_PAIR_CODE=ABCD-EFGH -e AUDIO_OUTPUT=alsasink \
  ghcr.io/fredhaa/beatballot:latest
```

Or use `compose.player.yaml`. The player keeps its token in its volume, so the
code is only needed once. If the player goes offline, voting carries on and the
music resumes when it's back; guests see "Speaker offline" meanwhile.

The landing page (`/beatballot/`) lists the parties, or goes straight to the only
one. Hide a party from it in the hub page.

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
| `mode` | `standalone` | `standalone`, `hub` or `player` |
| `party_name` | `Beat Ballot` | Standalone: the party's name. Hub: the first party's name |
| `hub_pin` | | Hub: the owner's PIN (manage parties, pair players, Tidal) |
| `hub_url` | | Player: the hub's address |
| `pair_code` | | Player: one-time code from the hub page |
| `player_name` | hostname | Player: name shown on the hub |
| `playlists` | | Playlist links or URIs for the random pool, comma or newline separated; empty = guest suggestions only |
| `pin` | `1234` | Guest PIN |
| `admin_pin` | | Host PIN; empty disables host controls |
| `candidates` | `3` | Random songs per round |
| `lock_before_end` | `20` | Seconds before the end of a song that voting locks |
| `carry_over` | `true` | Losing songs with votes carry over (host can toggle live) |
| `carry_min_votes` | `2` | Votes a loser needs to carry over |
| `max_suggestions_per_user` | `1` | Searched songs each guest may add per round |
| `search_schemes` | | URI schemes searched for suggestions; empty = every enabled backend |
| `public_url` | | Base URL of the app (e.g. `https://example.party/beatballot/`); party links and QR codes build on it |
| `trusted_proxies` | | Reverse proxy IPs/CIDRs whose `X-Forwarded-For` is trusted (for per-guest PIN rate limiting) |
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
<http://localhost:6680/beatballot/> (PIN `1234`, host PIN `9999`). With `--hub` it
runs two parties and the hub page (`#/hub`, hub PIN `0000`). For hot reload,
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
  parties.py   one PartyController per party (room)
  rooms.py     parties, PINs, player pairing codes and tokens
  player.py    adapter from Mopidy core to the small Player protocol
  remote.py    hub side of a remote player; resolves songs to stream URLs
  agent.py     player mode: connects to the hub and plays what it sends
  frontend.py  pykka actor + CoreListener; 250 ms ticker drives the parties
  web.py       Tornado: parties, hub owner API, player sockets, static app
  hub.py       thread-safe broadcast of each party's state to its guests
web/           Svelte 5 + Vite source
dev/demo.py    simulated party for UI work
```

Timing is position-based. Four times a second the frontend reads the playback
position and locks when `position ≥ end − lock window`. Seeks and pauses are
handled for free. Phones interpolate the countdown locally between server
updates.
