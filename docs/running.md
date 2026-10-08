# Running the read-only prototype

**Status:** v0.1 alpha. This is a local inventory prototype, not a production organiser. It doesn't fetch media database matches, generate NFOs, rename files or apply proposed changes.

## Requirements

Python 3.11 or later. The initial supported environment is Linux; other platforms may work but have not been validated. A browser is needed for the local dashboard.

## Install

```bash
git clone https://github.com/TABARC-Code/TABARC-Media-Organiser.git
cd TABARC-Media-Organiser
git switch design/local-first-foundation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m tabarc_media
```

Visit **http://127.0.0.1:8787** on the same machine. The service deliberately binds to localhost, not every network interface.

Run the automated checks with `python -m pytest -q`.

### Other options

```bash
tabarc-media --port 8788 --data-dir /path/to/empty/local/state-folder
```

The default catalogue path is `~/.local/share/tabarc-media-organiser/catalogue.sqlite3`. Set `TABARC_DATA_DIR` to change this without passing `--data-dir`. Keep it on reliable **local storage**, outside all media roots. SQLite files, job history and write-ahead logs will be created there.

## First scan

1. Enter a library name, the **absolute path on the machine running the service**, and one or more media types. Select any applications that use the files; they are labels only at this stage, not active server connections.
2. Select Quiet, Balanced or Fast. These profiles change the delay between indexing batches. Resource metrics and operating-system-level scheduling controls are not implemented yet.
3. Add the library and click **Scan library**. The background worker reads names, sizes, file types and modification timestamps. It does not read entire video streams or calculate full hashes.
4. The dashboard shows the number of indexed files, job history and sample filename suggestions. Suggestions use filename patterns only: they are not authoritative matches. There is **no Apply button**.

Paused scans recheck the folder from the beginning when resumed. Already catalogued files are updated in place. Incomplete or faulty scans never prune unseen files from the catalogue, which matters when a network share briefly disappears.

## Limitations

- A server-side directory picker, media database lookups, metadata sidecars, duplicate detection, watcher service, API keys, AI/MCP connections and Plex/Jellyfin refreshes are not available yet.
- The interface doesn't presently allow removing a library or editing its settings. The SQLite catalogue persists across restarts.
- Filename suggestions are simple, unverified previews and may omit multi-episode, anime and edition details; do not use them as a source of truth.
- File records are updated in batches; scans might take a while on large network shares. No performance claims have been established on large datasets.
- This is a localhost application without account authentication. **Do not expose it to the LAN or internet** using a reverse proxy without adding proper authentication and transport security.
- A read-only *application* does not make a writable filesystem mount read-only. Where possible, test against genuinely read-only media mounts or disposable fixtures.

Please report failing media scans with platform, Python version, filesystem type and an anonymised example path. Never post personal folder listings or API credentials in an issue.
