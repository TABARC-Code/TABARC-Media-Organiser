# Implementation roadmap

Status: proposal; passing criteria are mandatory.

## Milestone 0 — repo and design

- Project brief, architecture and security documentation, coding conventions, developer environment, tests and CI.
- Select an open-source licence before accepting contributed code.
- Reuse *ideas* from uploaded reference tools, not code without compatible licences.

## Milestone 1 — usable read-only MVP (in progress)

- Python 3.11+, FastAPI and lightweight local web UI; SQLite on local storage with the initial schema and a basic migration. Implemented as an alpha; accessibility still needs review.
- Setup wizard: multiple media/app selections, library root picker, safe operation mode, scanning intensity.
- Read-only filesystem inventory with ignore rules, resumable progress, pause/resume and rate limiting.
- ffprobe/ExifTool optional adapters with graceful absence handling (not implemented yet); no transcode and no full-file hashes by default.
- Dashboard: total files, type breakdown, unmapped files, recent scans, errors and saved settings.
- **Exit:** tested against fixture libraries, no changed media files, low-resource scan, restart-safe jobs.

## Milestone 2 — matching and change previews

- TMDB, TVmaze and Open Library providers first; TVDB and AniList optional later.
- Stable IDs, matching explanations, manual corrections and provider provenance.
- TV season numbering, specials, date-based programmes and anime-order support.
- Proposed folder and filename trees, conflict report and saved per-root naming profiles.
- **Exit:** known-good corpus of films, multi-episode series, anime and ebooks; no unsafe automatic matches.

## Milestone 3 — verified transactions and metadata

- Journalled same-volume renames, sidecar association, power-loss/restart recovery tests.
- NFO, OPF, JSON reference and artwork writing under explicit per-root policy.
- Plex/Jellyfin integration, targeted rescan, existing metadata preservation.
- **Exit:** acceptance tests verify reversibility within stated bounds, no accidental file loss.

## Milestone 4 — extended library ecosystem

- Calibre, Audiobookshelf, Kavita, Komga and Navidrome adapters.
- MusicBrainz/AcoustID, comic metadata, book editions, optional DDC numbers with provenance.
- Optional duplicate investigator and archival catalogue export.
- **Exit:** multi-app fixtures with independent naming/tag policies and no direct tampering with managed DBs.

## Milestone 5 — optional AI and MCP

- Local STDIO MCP adapter, authenticated Streamable HTTP, secure tunnel documentation.
- Read-only tool set first; plans and approvals protected by local transaction policy.
- Ollama/local model, Claude and cloud API adapters isolated behind the same interface.
- **Exit:** deliberate malicious metadata prompt-injection and permission-boundary tests.

## Milestone 6 — release hardening

- Linux/Docker release, Windows/macOS exploratory tests, installation wizard, migration tests.
- Authentication for optional LAN hosting, backup/restore UI, crash recovery, export and logs.
- Performance run over representative large datasets/NAS; document throughput, I/O and CPU measurements rather than guessing.
- **Exit:** reproducible release with CI, sample configuration and a conservative default.

### Development discipline

After each four meaningful changes, audit the diff, rerun focused unit tests and the full applicable regression suite. A phase is complete only after its stated exit tests have actually passed. Keep a human-readable changelog and mark blocked or untested hardware-dependent behaviours clearly.
