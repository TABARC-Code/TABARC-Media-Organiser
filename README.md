# TABARC Media Organiser

Author: TABARC-Code

A self-hosted catalogue for a media library that's grown faster than anyone's patience for naming things properly. Films, TV and ebooks first. Plex and Jellyfin get to read the results; they don't get to own them.

Right now it does one thing: it looks. It walks your library, records what's there, and asks ffprobe what each video actually is. It doesn't rename, move, tag or delete anything. That's deliberate. The renaming comes later, once there's a catalogue worth trusting and a plan you can read before anything happens.

## Principles

- Useful without AI. Scanning, matching against reference databases and file operations are deterministic.
- Local first. The catalogue lives on local disk, and your library is read where it sits.
- Preview before trust. Everything starts read-only, and changes come only from a plan you've read.
- No destructive automation. Originals are never deleted or overwritten automatically.
- More than one consumer. Plex and Jellyfin may share a storage root, so output will get per-app profiles.
- Portable records. Provenance, identifiers and history stay in the catalogue.

## Status

Stage 2 of six. It looks and it asks, but it still changes nothing on disk.

| Stage | What | State |
|---|---|---|
| 1 | Read-only inventory | Done |
| 2 | Identity: filename parsing, free sources, scoring, review queue | Built. Tried live on a small test library, not yet on a real NAS |
| 3 | Dry-run plans, transaction journal, rollback | Planned |
| 4 | NFO and reference files | Planned |
| 5 | Ebooks, Calibre, Dewey (verified or blank) | Planned |
| 6 | Reports and exports | Planned |

## Requirements

- Python 3.11 or newer (tested on 3.11, 3.12 and 3.13)
- ffprobe (part of FFmpeg), optional but you'll want it. Without it the scan still runs, it just can't tell you anything about the video streams.
- Linux, macOS and Windows. CI runs the tests on all three. Linux and macOS are the ones the author runs. Windows is new and its results are advisory until it has a real run behind it.
- The network-storage check works on Linux (mount table), macOS (`mount`) and Windows (drive type). If it can't tell what a path is on, it warns rather than passing quietly.

No Python packages needed at runtime. It's standard library all the way down, for now.

## Install

```bash
git clone <repo-url> tabarc-media-organiser
cd tabarc-media-organiser
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
```

## Docker

The image runs the same CLI with media mounted read-only:

```bash
docker compose build
docker compose run --rm tabarc-media init --roots /media/films --roots /media/tv
docker compose run --rm tabarc-media inventory
docker compose run --rm tabarc-media stats
```

Edit `docker-compose.yml` so the host paths point at your media. The `/media/...` paths inside the container must match the roots you pass to `init`. Keep `./config` on the Docker host's local disk, not on a network share. The catalogue is SQLite, and the tool refuses to open it on a network mount it can detect.

The config path can also be set with the `TABARC_CONFIG` environment variable.

## Configure

```bash
tabarc-media init --roots /mnt/nas/Movies /mnt/nas/TV /mnt/nas/Books
```

That writes `~/.config/tabarc-media/config.toml`, checked before it lands, and won't overwrite one that's already there. Leave out `--roots` and add them by hand under `[libraries]` if you'd rather. The commented template it starts from ships inside the package, so it works from a plain `pip install` too.

Things the loader will refuse, on purpose:

- relative paths
- the same root twice, or one root inside another (you'd get every file twice)
- the database inside a library root
- any key it doesn't recognise, so `media_extension` instead of `media_extensions` fails loudly instead of being quietly ignored

**Keep the database on local disk.** SQLite over SMB or NFS is a known way to corrupt it. The tool checks what the database path sits on (the mount table on Linux, `mount` on macOS, the drive type on Windows) and won't open a catalogue on a network share. If it can't tell, it warns instead of passing quietly.

## Run

```bash
tabarc-media inventory              # scan, with ffprobe
tabarc-media inventory --no-probe   # quick first pass, no ffprobe
tabarc-media stats                  # what the catalogue holds, per root, with total size
tabarc-media issues                 # what went wrong in the last scan
tabarc-media issues --scan 4        # ...or a specific one
tabarc-media identify               # look files up in the free sources
tabarc-media review                 # matches that need a person
tabarc-media review accept 12 --candidate 1
tabarc-media review reject 12
tabarc-media about                  # version, licence and data source credits
```

### Identifying files

`identify` reads the catalogue, parses each video and book path (using the folders when the file name says too little, so `Some Film (2019)/movie.mkv` and `Show/Season 2/S02E05.mkv` both work), asks the enabled sources, scores what comes back and records it. It never touches a media file.

A match is only marked `matched` when the title is strong, it clearly beats the runner-up, and nothing contradicts the file name. Two sources agreeing on the same work counts as one candidate, not a tie. Everything else goes to `pending` for you to look at, and a name with nothing to go on, like a bare `Dune.epub`, is searched but never accepted automatically. A file nothing close matches is `none`.

Your accept or reject is never overwritten by a later run. Results are reused for `max_age_days` (30 by default) and then refreshed, except that a result built while a source was down is retried on the next run. Set `offline = true` to make no lookups at all.

You must set `contact` under `[providers]` first, an email address is ideal. The free sources ask who is calling, and it goes in the User-Agent of every request. `identify` refuses to run without it.

`stats` is the quick way to check the catalogue agrees with what you think is on the box. Sizes are in binary units (GiB, TiB), which is what most NAS dashboards show.

Only one scan can run against a catalogue at a time. A second one is refused with a clear message. The lock belongs to the process, so a crash or `kill -9` can't leave it stuck, and a scan that died without finishing is marked `abandoned` next time round. (Locking uses `flock` on Linux and macOS and `msvcrt` on Windows. On a platform with neither, the scan refuses to start.)

The first full scan of a big NAS will take a while, mostly ffprobe. Later scans only probe files whose size or modified time changed, so they're much quicker. If you stop a scan with Ctrl-C, nothing's lost. Run it again and it picks up the expensive work where it left off.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Complete, no issues |
| 2 | Config or catalogue problem, or another scan already running. Nothing scanned |
| 3 | Complete, but some issues were recorded (for `identify`, a source failed) |
| 130 | Interrupted |

## What it records, and what it won't do

For every media file and sidecar (NFO, subtitles, artwork): path, size, modified time, kind, and for video the full ffprobe output.

It skips:

- symlinks, so it can't wander off the share or loop forever
- NAS and OS system folders: `@eaDir`, `#recycle`, `#snapshot`, `@Recycle`, `$RECYCLE.BIN`, `.snapshot` and so on (case-insensitive)
- macOS `._` files, which SMB shares love to leave lying around with a `.mkv` on the end

It reports, rather than ignores:

- folders it can't read
- an empty or missing root, usually a share that didn't mount
- filenames that aren't valid UTF-8 (recorded byte-for-byte, but later stages won't rename them)
- files ffprobe rejects

Files that vanish between scans are marked not present. They're never deleted from the catalogue. And if anything stopped a root being scanned completely, nothing in that root gets marked missing at all. An unmounted share looking like an empty library is exactly how a tool like this ruins someone's weekend.

## Metadata sources

The default sources need no key and no account:

- **Wikidata** for films, TV and books. CC0.
- **TVmaze** for TV. CC BY-SA 4.0, with credit to tvmaze.com. Anything you share that contains its data must carry the same licence.
- **Open Library** for ebooks. Its data licence hasn't been confirmed by this project yet, so check it for your own use.

`tabarc-media about` prints the credit lines for the sources you have enabled. IMDb's datasets are not used, since their terms rule out repackaging.

Optional keyed sources (TMDB, TheTVDB) are planned but **not built yet**. When they arrive, each user will bring their own key and the tool will stay off those sources until it finds one. Nothing is bundled, and keys never go in the repo, the logs or the catalogue.

## Tests

```bash
pytest -q
```

They run against throwaway folders in a temp directory, never a real library. CI runs them on Python 3.11, 3.12 and 3.13.

## Acknowledgements

Some of the Stage 2 design leans on ideas from [Ticket Booth](https://github.com/aleiepure/ticketbooth) by Alessandro Iepure (GPL-3.0-or-later, now archived). Ideas only, no code. Details in [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).

## Licence

MIT. See [LICENSE](LICENSE). Metadata providers have their own terms on rate limits, attribution and API access, so check those for your own use. Nobody's API keys ship with this.
