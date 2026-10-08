# Description

Author: TABARC-Code

A self-hosted, read-first catalogue for Plex and Jellyfin libraries. It walks a NAS, records every film, episode and ebook in a local SQLite index, and asks ffprobe what the video files really are. It's built so the boring, dangerous parts (renames, moves, metadata writes) only ever happen from a plan you've read first.

Currently at Stage 1: read-only inventory. No renaming yet. That's the point.

**Key bits**

- Read-only scan with ffprobe probing, resumable and cheap to re-run
- Reports unreadable folders and unmounted shares instead of quietly treating them as empty
- Never deletes catalogue rows; vanished files are marked, not forgotten
- Refuses to put its database on a network share
- Bring-your-own-key provider model (TMDB, TheTVDB opt-in) from Stage 2
- Standard-library Python, no runtime dependencies

Topics: plex, jellyfin, media-library, nfo, ffprobe, tmdb, thetvdb, nas, self-hosted, python
