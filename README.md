# TABARC Media Organiser

A local-first, low-resource media library organiser with a browser-based interface and optional AI integrations.

**Status:** Planning and foundation stage. No working media scanner or rename engine has been released yet.

## Purpose

Organise existing personal media libraries without making users manually rename every file or create every metadata record. Target types include films, television, anime, ebooks, audiobooks, music, comics and photographs. Designed to work alongside Plex, Jellyfin, Emby, Calibre, Audiobookshelf, Kavita, Komga and Navidrome, with independent folder-only operation.

## Principles

- **Useful without AI:** scanning, matching via configured reference databases, metadata generation and file operations must work deterministically.
- **Local-first:** the server, catalogue and all file operations run on the user's machine.
- **Quiet by default:** incremental scans, one low-priority worker, bounded I/O and backoff during system activity.
- **Preview before trust:** begin read-only; introduce narrowly scoped, verified automatic changes only after user opt-in.
- **No destructive automation:** don't delete or overwrite original media automatically.
- **Multiple consumers:** more than one media application may use the same storage root; use app-specific output profiles.
- **Optional AI:** an MCP tool interface plus adapters for cloud or local models, each restricted to approved operations.
- **Portable records:** store provenance, stable identifiers, file relationships, sidecars and history in a local catalogue.

## First milestone

A usable localhost setup wizard, media/app selection, root-folder configuration, SQLite catalogue, read-only incremental scanner, job progress and a proposed-change report. The first milestone **must not rename, move, delete or modify media files**.

See [product specification](docs/product-spec.md), [security and safety model](docs/security-and-safety.md) and [delivery plan](docs/roadmap.md) as development progresses.

## Development

The project uses UK English for documentation and messages. Claude Code and other coding agents should read `CLAUDE.md` before making changes. Do not claim that integration tests, metadata lookups or real filesystem operations have been validated unless they actually ran.

## Licence and external metadata

A project licence has not yet been selected. External metadata services have different rate limits, attribution requirements and API access terms. Keep provider adapters independent and never ship other people's API keys or proprietary classification schedules.

## Repository

[TABARC-Code/TABARC-Media-Organiser](https://github.com/TABARC-Code/TABARC-Media-Organiser)
