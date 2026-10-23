# TABARC Media Organiser, container image.
#
# Media is mounted read-only at /media. The config and catalogue live in the
# /config volume. Keep that volume on the Docker host's local disk, not on a
# network share, because SQLite is unsafe there. The CLI refuses a catalogue
# on a network mount it can detect.

FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY pyproject.toml LICENSE README.md ./
COPY src ./src
RUN pip install --no-cache-dir . \
 && rm -rf /src

RUN useradd --uid 1000 --create-home tabarc \
 && mkdir /config && chown tabarc:tabarc /config

# HOME is /config so that "~" in the default config points into the volume.
ENV HOME=/config \
    TABARC_CONFIG=/config/config.toml \
    PYTHONUNBUFFERED=1

USER tabarc
WORKDIR /config
VOLUME ["/config"]

ENTRYPOINT ["tabarc-media"]
CMD ["--help"]
