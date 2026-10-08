# Product specification — local-first media organiser

Status: design baseline. A basic read-only inventory alpha is implemented; integration, matching and write features are still planned. British English throughout.

## Product goal

A local web application at `http://127.0.0.1:8787` for managing existing personal media libraries. People choose **multiple media types**, **multiple consuming applications**, one or more approved folders, and a background-operation profile. The system discovers, indexes, matches, plans and eventually applies safe changes quietly. It must function without any LLM.

The library is an **index and organiser**, not a downloader, media player or new authority over Plex/Jellyfin database internals. A user can disconnect AI and all ordinary functions continue.

## Setup wizard

1. Select media types (checkboxes): Film, TV, Anime, Ebook, Audiobook, Music, Comics/Manga, Photographs, Home Video, Other.
2. Select applications (checkboxes, not exclusive radio buttons): Plex, Jellyfin, Emby, Calibre, Audiobookshelf, Kavita, Komga, Navidrome, Folder-only. Explain compatible output profiles and warn where two consumers need different conventions.
3. Add storage roots using a local folder picker, validate accessible mounts, and choose each root's read-only / sidecar / managed / staged-import policy. Never accept an arbitrary filesystem path from an AI tool as a capability.
4. Select naming profile, language, country/region, episode-order preference (aired/DVD/absolute), and metadata providers in priority order per media type.
5. Configure provider API keys with a test connection button. Providers without a required key must work without one. Store credentials through a secret manager, not ordinary settings JSON.
6. Select resource profile (Quiet / Balanced / Fast when idle) and automation policy (Review every change / Verified simple renames / Verified operations inside managed roots). Deletion stays disabled.
7. Optionally enable AI: none; local model through a tool-calling adapter; Claude or other compatible MCP clients; ChatGPT via supported custom MCP connection/tunnel; OpenAI/Anthropic API. Disclose external transmission before enabling.
8. Run a read-only preview. Show files discovered, unknown titles, possible matches, potential conflicts and proposed changes before enabling automation.

## Main screen

Top: last scan time, number of indexed files, current worker state, pending approvals, warnings. Cards for libraries, jobs, review queue, duplicates and settings. Keep jargon in an expandable Advanced panel. Include Pause / Resume / Cancel, with truthful per-job progress. Offer accessible keyboard navigation, high contrast and mobile-friendly layout.

## Recognition and naming

- Stage 1: filesystem inventory and existing sidecar IDs. Read filename, path, size, modification timestamp; avoid full hashes by default.
- Stage 2: parse and preserve candidate release information before cleaning: year, group tags, resolution, codec, language, edition, HDR/DV, subtitles, disc, scene/release markers.
- Stage 3: type-specific matching with internal tags, strong IDs, trusted filename/parent identifiers and remote provider evidence. Cross-source disagreement queues review; never treat a filename-only fuzzy title as verified.
- Stage 4: stable work / edition / physical-file identities; multiple copies, cuts, languages and qualities remain separate.
- Stage 5: propose target paths using rules for each consumer. Validate season numbering, anime air/DVD/absolute order, specials, multi-episode files, cartoons, documentaries, miniseries, anthologies and unusual names. `Season 00` often maps to specials; do not assume every `00` means specials. Preserve multi-episode structures.
- Stage 6: move associated subtitles, artwork, extras and sidecars together as a transaction. Do not strip a tag until its meaning has been recorded; keep edition and language information where it affects identity.
- Stage 7: emit canonical `media.json` + suitable NFO/OPF/ComicInfo.xml/XMP/embedded metadata when enabled. Never overwrite an existing user-edited NFO by default.

Illustrative shared film layout: `Movies/Arrival (2016)/Arrival (2016).mkv`; shared show layout: `TV Shows/Show (2019)/Season 01/Show (2019) - S01E01 - Episode Title.mkv`. Separate server output profiles must declare incompatibilities instead of mangling a shared folder.

## Integrations — media consumers

- Plex: read libraries and IDs with authorised API credentials; trigger a targeted rescan after a verified change. Preserve Plex agent and playback-state behaviour. Plex NFO handling requires explicit compatible agent configuration.
- Jellyfin: discover libraries, honor per-library providers and local NFO precedence; targeted refresh rather than repeated full rescans.
- Emby: optional alternative video adapter.
- Calibre: use supported Calibre APIs/CLI; **never** directly rename Calibre-managed internal folder paths.
- Audiobookshelf: audiobook, ebook, podcast and sidecar support; respect its own scan vs match behaviour.
- Kavita / Komga: EPUB/comic/manga formats, per-app file-layout conventions, ComicInfo metadata, refresh integration.
- Navidrome: tag-first music integration; artist/album names alone do not guarantee correct indexing.
- Folder only: supports unmanaged software and network shares with no API.

## Metadata sources

Each is a **separate optional provider adapter** with tests, caching, retry-after handling, attribution and configured rate limits:
- TMDB, TheTVDB, TVmaze for film/TV as appropriate.
- AniList and optional AniDB for anime. Do not invent a Cartoon Network provider: network/channel is metadata from supported TV/film sources.
- Open Library, Google Books and ISBN metadata sources for books.
- MusicBrainz and AcoustID for music fingerprints.
- Comic Vine / Metron if the user has permitted API access.
- ExifTool, ffprobe, MediaInfo, MKVToolNix, Calibre tools, Mutagen, image inspection for local extraction.

Provider keys can be blank and each provider must degrade gracefully when unreachable. Track record-source URL/id, retrieved timestamp, licence note and changes. Cache only as permitted.

## Classification

Use Dewey Decimal classifications where supported by verifiable source records. No copied proprietary DDC schedule. Classify other media with typed subjects, genres, year, author, series, network, artist and user-defined tags; never force a film or album into Dewey when inappropriate. Use an optional local AI model to suggest unverified subjects, not to silently overwrite verified ones.

## Background engine

- One logical inventory worker by default; bounded batch size and pagination.
- Persist jobs in local SQLite with resume cursors, cancellation and state transitions.
- On Linux apply lower CPU/IO priority (`nice`, `ionice` where supported) plus optional systemd/Docker cgroup limits. On Windows/macOS use relevant platform priority controls.
- Respect manual pause, configurable schedules, active playback/backup exclusion windows and free-space thresholds.
- Detect new files via filesystem watchers where reliable. On network shares use debounced, low-frequency reconciliation scans.
- Inspect large media with lightweight probes; compute full hashes only for verification or explicit duplicate actions. Never transcode during a normal organisation scan.
- Bound simultaneous provider calls per service and use exponential backoff.
- Process new stable files only: require unchanged file size/mtime for a configured settling period before considering a write.
- Idempotent rescans: unchanged, verified files should not be re-probed or re-renamed repeatedly.
- Measure task CPU usage, memory, disk I/O, network calls and error rate to support throttle policy.

## Matching and automation

Confidence is evidence-based and calibrated with a labelled validation corpus. Separate states: verified provider-ID match, sufficiently corroborated automatic candidate, ambiguous/manual review, and unknown/no change. Missing data or provider outage must not erase previously good metadata. Record why a file matched, its source IDs and manually protected corrections.

No automatic deletions. In safe automation, restrict to internal-root, collision-free, reversible renames with high-quality identity evidence. Moves between filesystems require verified copy-and-commit and capacity checks. API providers and AI models may propose but **cannot bypass** the transaction gate.

## MCP and AI adapter model

MCP is the tool **interface**, not the AI itself. Offer both local STDIO and authenticated Streamable HTTP transports as deployment permits.

Read tools: `library_status`, `list_libraries`, `search_media`, `inspect_media`, `list_issues`, `preview_changes`, `job_status`.
Privileged tools: `submit_plan_for_approval`, `apply_approved_plan`, `pause_jobs`, `resume_jobs`. These require separate local grants and user approval. No shell, arbitrary path reads, deletion or filesystem-wildcard powers. Default to read-only exposure.

The same application can use local model engines (e.g. Ollama) through an independent tool-calling AI adapter. A model without reliable tool calling is suggestion-only. Connecting a ChatGPT account to a private MCP service depends on product/plan support and may need Secure MCP Tunnel; the ordinary OpenAI API is separately billed and is not equivalent to the user's ChatGPT conversation.

## Data model

`libraries`, `roots`, `files`, `works`, `editions`, `identifiers`, `metadata_values`, `provider_responses`, `classifications`, `assets`, `match_candidates`, `proposals`, `operations`, `jobs`, `audit_events`, `settings`, `credential_refs`.

Store SQLite and thumbnails outside indexed media mounts. Use schema migrations and backups before upgrades. Separate logical metadata from original media bytes.

## Availability & portability

Initial target: Linux and Docker with localhost binding. Plan Windows and macOS packages after core filesystem behavior is tested. A network-accessible UI is an **explicit opt-in** and requires authentication and appropriately protected transport.
