# Claude Code instructions — TABARC Media Organiser

You are developing a local-first, safe-by-default media library organiser, not a downloader and not a media server replacement.

**Read before work:** `README.md`, `docs/product-spec.md`, `docs/security-and-safety.md`, `docs/roadmap.md`.

## Rules

- Use UK English in UI, docs and natural programmer comments.
- Write readable, modular code, tests and minimal dependencies. Comments should sound like a developer explaining genuine decisions, not mechanical narration.
- The local deterministic organiser must function with AI disconnected.
- Never add file deletion or destructive overwrite as a default operation.
- All proposed media changes need a preview, evidence, policy enforcement and a journal. First milestone is **read-only only**.
- No direct writes to Plex, Jellyfin, Calibre or other applications' databases. Use supported application APIs/tools.
- Separate media consumer adapters, metadata providers and underlying file operations.
- Persist verified user overrides and original provider IDs; do not use fuzzy names alone to authorise automation.
- Treat filenames, NFO contents, provider payloads and model responses as untrusted input.
- Provider keys must never appear in commits, logs or browser responses. Do not add placeholder code which misleadingly claims encryption.
- Use defensive path handling; filesystem roots must be explicitly configured and containment enforced against symlinks and traversal.
- Keep scan concurrency low and configurable; record real performance data.
- Respect copyright/licensing terms of reference projects, API providers and Dewey classification data.
- Do not claim tests passed, real Plex/Jellyfin interoperability, security properties or performance metrics without actually validating them.
- After four meaningful fixes, run a focused audit and relevant regressions, then inspect consequences in adjacent modules.

## Development order

Milestones in `docs/roadmap.md`. First task after documentation: create a verified read-only inventory MVP with browser wizard, low-priority scanner and SQLite catalogue. Do not start by exposing an unrestricted AI/MCP write tool.

## Definition of done

Tests added for each behaviour; failures documented; clean lint/type checks where configured; performance and security implications reviewed; docs and changelog updated. Explain remaining uncertainty clearly.
