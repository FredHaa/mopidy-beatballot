# syntax=docker/dockerfile:1.7
# Beat Ballot: Mopidy + Spotify/Tidal/SoundCloud + party voting. Builds for linux/arm64 (Raspberry Pi 4)
# and linux/amd64.

ARG PYTHON_IMAGE=ghcr.io/astral-sh/uv:python3.13-trixie-slim
ARG SPOTIFY_PLUGIN_VERSION=0.16.0-alpha+spotify-logging.b9abdbc

# --- 1. Svelte web app (runs natively on the build machine) -------------------
FROM --platform=$BUILDPLATFORM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build -- --outDir /static

# --- 2. Python environment (PyGObject is compiled here, not on the Pi) -------
FROM ${PYTHON_IMAGE} AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential pkg-config libgirepository-2.0-dev libcairo2-dev \
    && rm -rf /var/lib/apt/lists/*
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
COPY --from=web /static src/mopidy_beatballot/static
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- 3. Runtime -------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ARG TARGETARCH
ARG SPOTIFY_PLUGIN_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
        libgirepository-2.0-0 libcairo2 \
        gir1.2-glib-2.0 gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0 \
        gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-ugly \
        gstreamer1.0-plugins-bad gstreamer1.0-libav \
        gstreamer1.0-alsa gstreamer1.0-pulseaudio gstreamer1.0-tools \
    && tag="gst-plugin-spotify_$(echo "$SPOTIFY_PLUGIN_VERSION" | sed 's/+/%2B/g')" \
    && deb="gst-plugin-spotify_$(echo "$SPOTIFY_PLUGIN_VERSION" | sed 's/+/%2B/g')-0mopidy1_${TARGETARCH}.deb" \
    && curl -fsSL -o /tmp/spotify.deb \
        "https://github.com/mopidy/gst-plugins-rs-build/releases/download/${tag}/${deb}" \
    && apt-get install -y --no-install-recommends /tmp/spotify.deb \
    && gst-inspect-1.0 spotifyaudiosrc > /dev/null \
    && rm -rf /tmp/spotify.deb /var/lib/apt/lists/*

RUN useradd --system --uid 1000 --gid audio --home-dir /var/lib/mopidy --create-home mopidy
COPY --from=builder --chown=mopidy:audio /app/.venv /app/.venv
COPY docker/entrypoint.sh /entrypoint.sh

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    XDG_RUNTIME_DIR=/tmp
USER mopidy
WORKDIR /var/lib/mopidy
VOLUME /var/lib/mopidy
EXPOSE 6680
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD curl -fsS http://127.0.0.1:6680/beatballot/api/health || exit 1
ENTRYPOINT ["/entrypoint.sh"]
