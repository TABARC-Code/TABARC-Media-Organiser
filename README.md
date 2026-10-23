# TABARC Media Organiser

Author: TABARC-Code

A self-hosted catalogue for a media library that's grown faster than anyone's patience for naming things properly. Films, TV and ebooks first. Plex and Jellyfin get to read the results; they don't get to own them.

Right now it does one thing: it looks. It walks your library, records what's there, and asks ffprobe what each video actually is. It doesn't rename, move, tag or delete anything. That's deliberate. The renaming comes later, once there's a catalogue worth trusting and a plan you can read before anything happens.

## Status

Stage 1 of six. Read-only inventory only.

| Stage | What | State |
|---|---|---|
| 1 | Read-only inventory | Done |
| 2 | Identity: TMDB, filename parsing, review queue | Next |
| 3 | Dry-run plans, transaction journal, rollback | Planned |
| 4 | NFO and reference files | Planned |
| 5 | Ebooks, Calibre, Dewey (verified or blank) | Planned |
| 6 | Reports and exports | Planned |

## Requirements

- Python 3.12 or newer
- ffprobe (part of FFmpeg), optional but you'll want it. Without it the scan still runs, it just can't tell you anything about the video streams.
- Linux is what it's tested on. macOS should work but the network-filesystem check won't run there.

No Python packages needed at runtime. Honestly, it's standard library all the way down for now.

## Install

```bash
git clone <repo-url> tabarc-media-organiser
cd tabarc-media-organiser
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
```

## Configure

```bash
mkdir -p ~/.config/tabarc-media
cp config/default.toml ~/.config/tabarc-media/config.toml
```

Then edit the copy. At minimum, set your roots:

```toml
[libraries]
roots = ["/mnt/nas/Movies", "/mnt/nas/TV", "/mnt/nas/Books"]
```

Things the loader will refuse, on purpose:

- relative paths
- the same root twice, or one root inside another (you'd get every file twice)
- the database inside a library root
- any key it doesn't recognise, so `media_extension` instead of `media_extensions` fails loudly instead of being quietly ignored

**Keep the database on local disk.** SQLite over SMB or NFS is a known way to corrupt it. On Linux the tool checks the mount table and won't open a catalogue on cifs, nfs and friends. On other systems it can't check, so that one's on you.

## Run

```bash
tabarc-media inventory              # scan, with ffprobe
tabarc-media inventory --no-probe   # quick first pass, no ffprobe
tabarc-media issues                 # what went wrong in the last scan
tabarc-media issues --scan 4        # ...or a specific one
```

The first full scan of a big NAS will take a while, mostly ffprobe. Later scans only probe files whose size or modified time changed, so they're much quicker. If you stop a scan with Ctrl-C, nothing's lost. Run it again and it picks up the expensive work where it left off.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Complete, no issues |
| 2 | Config or catalogue problem, nothing scanned |
| 3 | Complete, but some issues were recorded |
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

## Metadata providers (from Stage 2)

Bring your own keys. Every user needs their own account with each provider. Nothing is bundled, and keys never go in the repo, the logs or the catalogue.

- **TMDB.** Free key for non-commercial use. This product uses the TMDB API but is not endorsed or certified by TMDB.
- **TheTVDB.** Opt-in. You'll need your own TheTVDB account and API key, and a subscription PIN if your key type requires one. Read their terms for your own use. Not my call to make for you.

## Tests

```bash
pytest -q
```

57 tests. They run against throwaway folders in a temp directory, never a real library.

## Acknowledgements

Some of the Stage 2 design leans on ideas from [Ticket Booth](https://github.com/aleiepure/ticketbooth) by Alessandro Iepure (GPL-3.0-or-later, now archived). Ideas only, no code. Details in [ACKNOWLEDGEMENTS.md](ACKNOWLEDGEMENTS.md).

## Licence

None yet, so all rights reserved by default. That'll change before this goes public.
