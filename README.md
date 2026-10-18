# Beat Ballot

Party guests vote on the next song from their phones. A
[Mopidy](https://mopidy.com) extension with a mobile web app, for one party at
home or many parties on a server, each playing on its own speaker.

- **Random picks plus guest suggestions.** Each round puts random songs from your
  Spotify, Tidal and/or SoundCloud playlists on the ballot, and guests search every
  enabled service to add their own. A song you add starts with your vote.
- **Voting locks 20 seconds before the current song ends.** The song with the most
  votes plays next.
- **Losing songs with 2+ votes carry over** to the next round, votes kept. Songs that
  drop off a ballot come back later as random picks, more often than playlist songs.
- **Invite friends** from your phone: the share button sends the link with the PIN
  filled in through Messenger, SMS and so on. Or leave the PIN out for an open party.
- **A big-screen view** with a QR code to join, which fills any TV, landscape or
  portrait.
- **Hub and players:** one server hosts many parties, each playing on a player at the
  venue: a browser tab, a Raspberry Pi with the `.deb` package, or Docker. Players
  need no music accounts; the hub sends them one stream at a time.
- **Test mode** plays 30 seconds per song and locks after 15, to try things quickly.

## How a party works

| Situation | What happens |
| --- | --- |
| You vote | One vote per guest. Voting for another song moves your vote |
| You tap your vote again | It's withdrawn |
| You add a song (search) | It joins the ballot with your vote. One per guest per round by default |
| The ballot is full (host's limit) | New songs are refused; adding one that's already there counts as a vote |
| Tie | The song that reached that count first wins |
| Nobody voted | A random pick from the round wins |
| A song loses with 2+ votes | It carries over to the next round with its votes (the host can turn this off) |
| A song loses with fewer votes | It drops off. Guests' songs join the random pool for later rounds |
| The music stops with nothing queued | The current leader plays straight away |
| A song won't play (removed from the service, say) | It's skipped and the next one plays |

**The random picks** come from all the party's playlists combined (a song on two
services counts once) plus the songs that dropped off earlier ballots:

- One pick per round is always a dropped song, when there is one. The other picks
  favour dropped songs 3 to 1 over playlist songs (`BALLOT_DISCARDED_WEIGHT`).
- A song that just dropped off never shows up on the very next ballot.
- Playlist songs that lost count as shown, so the rest of the playlist comes first.
- Without playlists, the party runs on guest suggestions alone; the music starts with
  the first one.

## Guests and hosts

**Guests** open the party link (or scan the QR code), pick a name and enter the PIN.
Parties without a guest PIN are open: a name is enough, and an "I'm the host" link on
the join page asks for the host PIN.

**The host** joins with the host PIN and gets host controls: pause and skip, test
mode, carry-over on or off, random picks per round (0-10), the most songs on a ballot
(0 = no limit), the playlists, and removing songs from the ballot. On a hub, hosts can
also make their browser the party's speaker.

**The big screen** (`…#/host`, linked at the bottom of the party page) shows what's
playing, the countdown, the ballot and a QR code with the PIN. It sizes itself to the
screen; A− / A+ in the corner (or the `+`, `-` and `0` keys) adjust it per screen.

## Three ways to run it

| Mode | What it does | Typical setup |
| --- | --- | --- |
| `standalone` (default) | One party; voting and music on the same machine | A Pi or PC with speakers at home |
| `hub` | Many parties; voting, search and logins on a server, which plays nothing itself | A server behind your domain |
| `player` | Plays what its hub sends | A browser, a Pi or a PC with speakers at each venue |

Choose with `BALLOT_MODE`. The same Docker image does all three.

## Music services

| Service | Setup | Notes |
| --- | --- | --- |
| **Tidal** | Nothing in `.env`. On first start, log in from the host controls (standalone) or the hub page (hub), or with the `link.tidal.com` link in the log | The session is kept in the data folder. `TIDAL_QUALITY` defaults to `LOSSLESS` |
| **Spotify** | `SPOTIFY_CLIENT_ID`/`SECRET` from <https://mopidy.com/ext/spotify/#authentication>. Needs Premium | Standalone only: remote players can't stream Spotify. Use playlists you own (Spotify blocks API access to its editorial playlists). Streaming currently fails for some accounts ([librespot#1649](https://github.com/librespot-org/librespot/issues/1649)) |
| **SoundCloud** | `SOUNDCLOUD_AUTH_TOKEN` from <https://mopidy.com/ext/soundcloud/#authentication> | Playlists are sets: `https://soundcloud.com/<user>/sets/<name>` |

Enable them with `MUSIC_BACKENDS`, e.g. `tidal` or `spotify,tidal,soundcloud`.
Playlists are share links (or Mopidy URIs) in `BALLOT_PLAYLISTS`, comma-separated, or
one per line in the host controls. Search covers every enabled service and
alternates their results; each song shows a small badge for its service.

If 3 songs in a row from one service fail, that service is left out of the random
picks for 10 minutes and the host controls say so; the party carries on with the
others. Beat Ballot runs Tidal's device login itself and shows the link only to the
host (whoever opens it connects their account), so a pending login never freezes
Mopidy.

## Quick start: one party on a Pi with Docker

You need 64-bit Raspberry Pi OS, Docker, and a Tidal, Spotify Premium and/or
SoundCloud account.

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

1. **Audio output:** run `aplay -l` and set `AUDIO_OUTPUT`, e.g.
   `alsasink device=hw:Headphones` (3.5 mm jack), `alsasink device=hw:vc4hdmi0`
   (HDMI) or `alsasink device=hw:1,0` (USB DAC). On a desktop with PipeWire, use
   `pulsesink` and mount its socket (see `compose.yaml`).
2. **Links and QR code:** set `BALLOT_PUBLIC_URL=http://<pi-ip>:6680/beatballot/`.
   A container can't reliably find its own address.
3. Open `http://<pi-ip>:6680/beatballot/` and join with the host PIN. The big screen
   is at the bottom of the party page.

Try `BALLOT_TEST_MODE=true` first: rounds take 30 seconds, so you see the whole flow
quickly. Hosts can also switch test mode on and off live.

## Hub and players

The hub hosts parties at `https://<hub>/beatballot/r/<party>/`. Each has its own name,
PINs, QR code and ballot, and plays on one player. The landing page
(`/beatballot/`) lists the parties, or goes straight to the only one.

**Set up the hub** (`compose.yaml` on your server, typically behind a reverse proxy):

```sh
BALLOT_MODE=hub
BALLOT_HUB_PIN=…                 # the hub owner's PIN
MUSIC_BACKENDS=tidal             # and/or soundcloud
BALLOT_PUBLIC_URL=https://www.example.party/beatballot/
BALLOT_TRUSTED_PROXIES=…         # your proxy's IPs, so PIN rate limiting works
# Optional: BALLOT_PARTY_NAME/BALLOT_ADMIN_PIN (and BALLOT_PIN) create a first party
```

Open `https://<hub>/beatballot/#/hub` and log in with the hub PIN to connect Tidal,
create parties (PINs are random unless you choose them; tick "Open party" for no
guest PIN), pair players, and see each party's player and what's playing. Changing a
party's PINs signs that party's guests out. Only expose `/` and `/beatballot` through
your proxy: Mopidy's own API at `/mopidy/` controls playback.

**Players** connect out to the hub, so they work behind any router. The hub logs in
to the music services; for each song it sends the player a short-lived stream URL
(Tidal's last about an hour) and nothing else.

| Player | Best for | Setup |
| --- | --- | --- |
| **Browser** | Any laptop, tablet or TV browser | Nothing to install. Join the party with the host PIN, press **Play on this device** in the host controls, then **Start playing here** |
| **.deb package** | A Raspberry Pi or Linux box that stays put | See below |
| **Docker** | Anything that runs Docker | The `docker run` command on the hub page (Pair player), or `compose.player.yaml` |

A party has one player at a time. A host's browser can take over from another player
(it warns first); the replaced player goes quiet and checks back now and then, so it
takes over again once the browser stops. While a party has no player, voting carries
on and guests see "Speaker offline"; the music resumes when it's back.

**Browser player.** Keep the tab open, the screen on (it asks the browser to stay
awake) and the charger in. Phones pause background tabs, so a laptop, tablet or TV
works best. The next song preloads, so there's barely a gap. Volume is on the speaker
page, and leaving the page stops the music. Tidal plays in all current browsers;
SoundCloud songs that only stream as HLS may not play outside Safari.

**.deb package**, for Debian 13 and Raspberry Pi OS "trixie" or newer (and other
distros with Python 3.13+), amd64 and arm64, from
[Releases](https://github.com/FredHaa/mopidy-beatballot/releases). Get a pairing code
from the hub page (Pair player), then:

```sh
sudo apt install ./beatballot-player_0.2.0_arm64.deb
sudo beatballot-player pair ABCD-EFGH https://www.example.party   # starts the service
beatballot-player status        # connected, and to which party?
beatballot-player logs          # follow the log
sudo beatballot-player unpair   # stop and forget the party
```

It runs as a service and starts on boot; settings (hub, name, sound output, volume)
are in `/etc/beatballot-player/player.conf`. On a desktop with PipeWire or
PulseAudio, only your own session reaches the sound card: run the same commands
without `sudo` for a per-user service (settings in `~/.config/beatballot-player/`).
The package installs Mopidy and Beat Ballot in `/opt/beatballot-player` on top of the
system's GStreamer and PyGObject. Older releases (Raspberry Pi OS Bookworm, Ubuntu
24.04) have a Python too old for Mopidy 4; use the browser or Docker player there.

**Docker player:** the hub page's command, or `compose.player.yaml` with
`BALLOT_HUB_URL` and `BALLOT_PAIR_CODE`. The token stays in the volume, so the code
is only needed once.

## Releases

Pushing a tag `vX.Y.Z` (matching `pyproject.toml`'s version) publishes:

- a GitHub Release with the `.deb` packages for amd64 and arm64, the Python wheel and
  the source package (`.github/workflows/release.yml`),
- the Docker image `ghcr.io/fredhaa/beatballot` tagged `X.Y.Z` (every push to `main`
  also updates `latest`),
- the wheel on PyPI, once trusted publishing is set up on PyPI and the repository
  variable `PYPI_PUBLISH` is `true`.

Build things yourself:

```sh
packaging/deb/build.sh amd64 arm64     # .deb packages (Docker; QEMU for other arches)
docker buildx build --platform linux/arm64 -t beatballot .   # the image
```

The image is based on `ghcr.io/astral-sh/uv:python3.13-trixie-slim`, with all music
services, the prebuilt `gst-plugin-spotify` from
[mopidy/gst-plugins-rs-build](https://github.com/mopidy/gst-plugins-rs-build), and
the GStreamer codecs Tidal and SoundCloud need. Extra Mopidy settings can be mounted
at `/etc/mopidy/extra.conf` (see `compose.yaml`).

As a Python package, `mopidy-beatballot` installs without music services (enough for
a player); add `[tidal]`, `[spotify]`, `[soundcloud]` or `[all]`.

## Configuration

The `[beatballot]` section of Mopidy's config. With Docker, set the `BALLOT_*`
variable instead.

| Key | Docker variable | Default | |
| --- | --- | --- | --- |
| `mode` | `BALLOT_MODE` | `standalone` | `standalone`, `hub` or `player` |
| `party_name` | `BALLOT_PARTY_NAME` | `Beat Ballot` | Standalone: the party's name. Hub: the first party's name |
| `pin` | `BALLOT_PIN` | `1234` (Docker: none) | Guest PIN. Empty: an open party, a name is enough |
| `admin_pin` | `BALLOT_ADMIN_PIN` | | Host PIN; empty disables host controls |
| `hub_pin` | `BALLOT_HUB_PIN` | | Hub: the owner's PIN (parties, players, Tidal) |
| `hub_url` | `BALLOT_HUB_URL` | | Player: the hub's address |
| `pair_code` | `BALLOT_PAIR_CODE` | | Player: one-time code from the hub page |
| `player_name` | `BALLOT_PLAYER_NAME` | hostname | Player: name shown on the hub |
| `playlists` | `BALLOT_PLAYLISTS` | | Playlist links or URIs, comma or newline separated; empty: guest suggestions only |
| `candidates` | `BALLOT_CANDIDATES` | `3` | Random picks per round, 0-10 (hosts can change it live) |
| `max_ballot` | `BALLOT_MAX_BALLOT` | `0` | Most songs on a ballot, counting everything; 0 = no limit (hosts can change it live) |
| `discarded_weight` | `BALLOT_DISCARDED_WEIGHT` | `3` | How much likelier dropped songs are as random picks than playlist songs; 1 = equally |
| `carry_over` | `BALLOT_CARRY_OVER` | `true` | Losing songs with votes carry over (hosts can toggle it live) |
| `carry_min_votes` | | `2` | Votes a losing song needs to carry over |
| `max_suggestions_per_user` | | `1` | Songs each guest may add per round |
| `lock_before_end` | `BALLOT_LOCK_BEFORE_END` | `20` | Seconds before the end of a song that voting locks |
| `test_mode` | `BALLOT_TEST_MODE` | `false` | Play `test_play_seconds`, lock at `test_lock_at` |
| `test_play_seconds` | | `30` | |
| `test_lock_at` | | `15` | |
| `search_schemes` | | | URI schemes searched for suggestions; empty: every enabled service |
| `public_url` | `BALLOT_PUBLIC_URL` | | Base URL of the app (e.g. `https://example.party/beatballot/`); party links and QR codes build on it |
| `trusted_proxies` | `BALLOT_TRUSTED_PROXIES` | | Reverse proxy IPs/CIDRs whose `X-Forwarded-For` is trusted, for per-guest PIN rate limiting |

Docker-only variables: `MUSIC_BACKENDS` (`spotify`, `tidal`, `soundcloud`,
comma-separated, or `none`), `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`,
`SPOTIFY_BITRATE`, `TIDAL_QUALITY`, `SOUNDCLOUD_AUTH_TOKEN`, `AUDIO_OUTPUT`,
`MIXER_VOLUME` and `MOPIDY_VERBOSITY`. See `.env.example`.

## Development

```sh
# Python. Mopidy needs GStreamer and PyGObject from the system:
sudo apt install python3-gi gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
    gstreamer1.0-plugins-good
uv venv --system-site-packages
uv sync --all-extras --no-install-package pygobject --no-install-package pycairo
uv run pytest

# Web app
cd web && npm install && npm run build   # outputs to src/mopidy_beatballot/static
```

**UI without Mopidy:** `uv run python dev/demo.py` serves the real web app and vote
engine against a simulated player with a few bot voters. Open
<http://localhost:6680/beatballot/> (PIN `1234`, host PIN `9999`). With `--hub` it
runs two parties and the hub page (`#/hub`, hub PIN `0000`). For hot reload, run
`npm run dev` in `web/` at the same time; Vite proxies the API and WebSocket to port
6680 (override with `MOPIDY_URL`).

### Layout

```
src/mopidy_beatballot/
  voting.py      vote engine: ballots, ties, carry-over (pure Python)
  pool.py        random picks: playlists plus dropped songs, without repeats
  party.py       rounds, lock-in timing, test mode, queueing (Mopidy-free)
  parties.py     one PartyController per party (room)
  rooms.py       parties, PINs, player pairing codes and tokens
  backends.py    service names and playlist share links
  tidal_auth.py  Tidal device login without blocking Mopidy; fast Tidal search
  player.py      adapter from Mopidy core to the small Player protocol
  remote.py      hub side of a remote player; resolves songs to stream URLs
  agent.py       player mode: connects to the hub and plays what it sends
  frontend.py    pykka actor + CoreListener; 250 ms ticker drives the parties
  web.py         Tornado: parties, hub owner API, player sockets, static app
  hub.py         thread-safe broadcast of each party's state to its guests
web/             Svelte 5 + Vite app (web/src/lib/speaker.svelte.js: the browser player)
packaging/deb/   the beatballot-player .deb: command, systemd units, build scripts
docker/          the image's entrypoint
dev/demo.py      simulated parties for UI work
```

Timing is position-based: four times a second the frontend reads each party's
playback position and locks when `position ≥ end − lock window`, so seeks and pauses
need no special handling. Phones interpolate the countdown between server updates.
