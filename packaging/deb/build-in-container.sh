#!/bin/sh
# Builds the .deb inside debian:trixie for the container's architecture.
# Mounts: /src (this directory), /dist (the wheel), /out (where the .deb goes).
set -eu
VERSION=$1
ARCH=$(dpkg --print-architecture)
VENV=/opt/beatballot-player
STAGE=/tmp/stage

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-pip python3-gi python3-cairo ca-certificates > /dev/null

# A venv on the system Python, seeing the system's PyGObject (GStreamer's
# Python bindings can't sensibly be built from PyPI on every device).
python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --no-cache-dir --disable-pip-version-check \
    "/dist/mopidy_beatballot-$VERSION-py3-none-any.whl"
if [ -d "$VENV/lib/python3"*/site-packages/gi ]; then
    echo "pip installed its own PyGObject; the system one should be used" >&2
    exit 1
fi
"$VENV/bin/python" -c "import mopidy_beatballot, mopidy.config, gi"
"$VENV/bin/pip" uninstall --quiet --yes pip  # Not needed at runtime.
find "$VENV" -name __pycache__ -prune -exec rm -rf {} +
"$VENV/bin/python" -m compileall -q "$VENV/lib" > /dev/null

PY=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
NEXT=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1] + 1}")')

rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt" "$STAGE/usr/bin" "$STAGE/etc/beatballot-player" \
    "$STAGE/usr/lib/systemd/system" "$STAGE/usr/lib/systemd/user" \
    "$STAGE/usr/share/doc/beatballot-player"
cp -a "$VENV" "$STAGE/opt/"
install -m 755 /src/beatballot-player "$STAGE/usr/bin/"
install -m 644 /src/player.conf "$STAGE/etc/beatballot-player/player.conf"
install -m 644 /src/beatballot-player.service "$STAGE/usr/lib/systemd/system/"
install -m 644 /src/beatballot-player.user.service \
    "$STAGE/usr/lib/systemd/user/beatballot-player.service"
install -m 755 /src/postinst /src/prerm /src/postrm "$STAGE/DEBIAN/"
echo /etc/beatballot-player/player.conf > "$STAGE/DEBIAN/conffiles"
cat > "$STAGE/usr/share/doc/beatballot-player/copyright" <<EOF
Beat Ballot player $VERSION, https://github.com/FredHaa/mopidy-beatballot
Licensed under the Apache License 2.0. Bundled Python packages keep their own licenses.
EOF

SIZE=$(du -sk "$STAGE" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<EOF
Package: beatballot-player
Version: $VERSION
Architecture: $ARCH
Maintainer: Frederik Haarslev <FredHaa@users.noreply.github.com>
Installed-Size: $SIZE
Section: sound
Priority: optional
Homepage: https://github.com/FredHaa/mopidy-beatballot
Depends: python3 (>= $PY), python3 (<< $NEXT), python3-gi (>= 3.50), python3-cairo,
 gir1.2-gstreamer-1.0, gir1.2-gst-plugins-base-1.0, gstreamer1.0-plugins-base,
 gstreamer1.0-plugins-good, gstreamer1.0-plugins-ugly, gstreamer1.0-plugins-bad,
 gstreamer1.0-libav, gstreamer1.0-alsa, gstreamer1.0-pulseaudio, adduser
Description: Beat Ballot party player
 Plays a Beat Ballot hub's party on this machine's speakers. Party guests vote
 on the next song from their phones; the hub sends this player one stream at a
 time, so the player needs no music service accounts.
 .
 Pair it with a code from the hub page: sudo beatballot-player pair CODE HUB_URL
EOF

mkdir -p /out
DEB="/out/beatballot-player_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB" > /dev/null
chown "$(stat -c '%u:%g' /out)" "$DEB"  # Hand it back to whoever owns /out.
echo "built $DEB ($SIZE KiB installed)"
