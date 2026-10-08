# TABARC Media Organiser

**A local media librarian for people who've got better things to do than rename the same television series for the third time.**

TABARC Media Organiser is a planned, self-hosted application for sorting and maintaining film, television, anime, book, audiobook, music and other media collections. The aim is fairly ordinary: point it at the folders you already use, tell it which media applications you run, and let it work out what belongs where. It should identify titles, clean up filenames, arrange episodes and editions correctly, retrieve metadata and prepare compatible sidecar files without demanding an evening of manual housekeeping.

Most of that work should happen quietly in the background. The browser interface is there to configure libraries, see what the organiser has found and deal with genuine ambiguities — not to make the user supervise every file.

> **Project status — v0.1 alpha, read-only prototype.** A local web dashboard, persistent SQLite catalogue, incremental scanner, scan controls and filename-pattern previews are now in development on the draft branch. This is **not** a finished organiser: media database matching, NFO creation, renaming, duplicate management, server integrations and AI connections are still planned. The preview does not write to media files.

## What it's for

A media folder rarely stays tidy by accident. One season arrives as `Series.S02.1080p.WEB-DL`, another is buried under its release-group name, and a special episode is sitting in Season 01 because that's where somebody happened to put it. Meanwhile, a film might exist in both theatrical and extended versions, or the audiobook and ebook of the same title may have been given entirely different names.

The organiser should recognise those distinctions before it starts moving things around. A release label may be disposable; an edition, language, subtitle association or episode order is not. The intention isn't to flatten everything into pretty filenames at the expense of useful information.

### Planned capabilities

- **Find and catalogue existing files.** Scan approved folders, read available technical and embedded metadata, and record which files have already been checked.
- **Match the actual title.** Use established media databases and existing identifiers, with review for conflicting or uncertain results.
- **Tidy names and folders.** Apply configurable conventions for films, series, seasons, episodes, specials, anime and multi-part releases.
- **Look after related files.** Keep subtitles, artwork, extras, NFOs and other sidecars associated with the right item.
- **Generate portable metadata.** Produce appropriate NFO, OPF, ComicInfo.xml, XMP or JSON reference records rather than treating a media server's internal database as the only copy.
- **Handle editions properly.** Keep separate cuts, resolutions, languages, book editions and formats where those differences matter.
- **Identify duplicate candidates.** Distinguish exact duplicates from alternate encodes and genuinely different editions. Nothing gets deleted automatically.
- **Classify books and reference material.** Preserve available Dewey Decimal classifications with source attribution, alongside ordinary subjects and user-defined categories.
- **Run gently.** Work incrementally, use low-priority background jobs and throttle expensive operations instead of monopolising a NAS.
- **Offer optional AI assistance.** Expose approved catalogue operations through MCP or a provider interface for local and remote models. Basic organisation must never depend on an AI service.

## Choose the applications you use

The intended setup is a local webpage, with checkboxes for **multiple** media types and **multiple** applications. Running Plex and Jellyfin against the same film library is normal; the organiser shouldn't force you to choose one or pretend their metadata rules are identical.

| Library | Planned integrations and formats |
| --- | --- |
| Films and television | Plex, Jellyfin, Emby; NFO and artwork |
| Anime and cartoons | Series and episode-order matching, including appropriate anime data sources |
| Ebooks | Calibre, Kavita; EPUB/PDF metadata, OPF and book references |
| Audiobooks and podcasts | Audiobookshelf; chapters, authors, narrators and associated editions |
| Music | Navidrome and other tag-based libraries; artist, album, track and recording IDs |
| Comics and manga | Kavita, Komga; ComicInfo.xml and series/issue metadata |
| Photographs and home videos | ExifTool, MediaInfo, FFprobe; capture dates, technical details and optional location metadata |
| Other folders | Standalone cataloguing without a media-server connection |

These are **integration targets**, not a claim that connectors already exist. Each will have its own tested adapter, and a folder-only setup must remain available for users who don't run any of the named software.

## A typical clean-up

For example, the organiser might find:

```text
Incoming/
└── Example.Show.S02E03.1080p.WEB-DL.x265-GROUP.mkv
```

After matching the correct series and episode, a naming profile could propose:

```text
TV Shows/
└── Example Show (2021)/
    └── Season 02/
        ├── Example Show (2021) - S02E03 - Episode Title.mkv
        └── Example Show (2021) - S02E03 - Episode Title.nfo
```

The titles and dates here are placeholders, not real database results. The original filename, edition and technical information would remain in the catalogue even where the display name becomes shorter. The NFO would only be generated once the corresponding feature is enabled and its metadata verified.

A badly matched file should go into a review queue. Calling an episode something confidently doesn't make it the right episode.

## How it should work

1. Open the local dashboard and select the types of media you keep.
2. Tick the applications that use those libraries, then add the folders the organiser is allowed to inspect.
3. Choose naming conventions, metadata providers, processing limits and whether changes need individual approval.
4. Let the scanner build its local catalogue. Initial discovery reads files and reports findings without touching the collection.
5. Review uncertain matches and proposed changes. Later releases will support carefully limited automatic renames where the identity and operation are properly verified.

The background service is intended to carry on when the browser is closed. It will use a local SQLite catalogue, resumable jobs and modest concurrency; a full hash of every large video file is not an acceptable starting point for routine scanning.

### Safe by default

The first milestone is **read-only**. Later, the organiser will use a transaction journal, collision checks and explicit per-folder permissions before making authorised changes. Existing metadata and human corrections should survive a fresh scan. Originals will not be automatically deleted or overwritten.

A fast guessed match is still a guess. An uncertain result belongs in the review queue, not quietly filed under a plausible but incorrect title.

For the full design, see [product specification](docs/product-spec.md) and [security and safety](docs/security-and-safety.md).

## Database providers and optional AI

The planned metadata adapters include TMDB, TheTVDB, TVmaze, AniList, suitable book catalogues such as Open Library, MusicBrainz and other media-specific sources. Some providers require individual API keys or have usage conditions. The application will expose those settings in the GUI, keep credentials out of normal configuration files and provide sensible fallbacks when a service is unavailable.

AI is optional by design. A local model, Claude or ChatGPT could help review ambiguous matches, suggest subjects or inspect a catalogue report through a restricted MCP interface. It should not get an unrestricted shell, be given the whole filesystem or be able to bypass the organiser's own file-operation checks. Disabling AI must not disable the librarian.

## Performance and installation

The eventual deployment target is a local web service, initially on **Linux or Docker**, with a browser-based interface bound to localhost by default. Windows and macOS packaging can follow after the file-handling core has been tested across platforms.

There will be selectable **Quiet**, **Balanced** and **Fast when idle** profiles. These remain design targets until there are actual benchmarks; network storage rarely behaves as conveniently as a local SSD.

### Try the read-only prototype

The initial Python service is on the `design/local-first-foundation` branch, pending review. With Python 3.11 or later on Linux:

```bash
git clone https://github.com/TABARC-Code/TABARC-Media-Organiser.git
cd TABARC-Media-Organiser
git switch design/local-first-foundation
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
python -m tabarc_media
```

Open `http://127.0.0.1:8787` on the same machine. Add an existing absolute media folder, choose its types and applications, and start a read-only scan. The selected application names are labels only in this release — no connection to Plex or Jellyfin is attempted. Review the [running instructions](docs/running.md) before pointing it at valuable data.

This prototype provides a basic setup form rather than a complete first-run wizard, and it has no NFO exporter or automatic rename facility. The [roadmap](docs/roadmap.md) records what's next.

## Development

This project is being developed under **TABARC-Code**. The immediate work is the filesystem inventory and matching groundwork, not an elaborate AI control panel. The latter is worth doing, but only after the application understands what it's looking at.

See [description.md](description.md) for the longer project brief and design reasoning, and [the roadmap](docs/roadmap.md) for the staged build. Development notes and code comments use UK English and explain actual decisions, limitations and odd cases encountered along the way.

Contributions, issue reports and corrections are welcome once there is something concrete to run or review. A licence still needs to be chosen; until then, don't assume the repository is released under an open-source licence simply because it is public.
