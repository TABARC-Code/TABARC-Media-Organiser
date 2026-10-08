# TABARC Media Organiser — Project Description

## The idea

Sorting media folders isn't particularly difficult work. It's repetitive, fussy and surprisingly easy to get wrong. A title has been abbreviated, one episode belongs to a different season order, or a file has picked up six bits of technical shorthand that were useful at the time and are now just clutter. Multiply that by a sizeable film, television, book or music collection and what should be a straightforward filing job becomes an ongoing chore.

**TABARC Media Organiser** is intended to deal with that problem locally. It's a self-hosted, browser-controlled librarian that works out what a media file actually is, records the supporting information, and proposes or performs the right organisational work according to the user's settings. Routine jobs should run unattended without giving the software licence to rearrange an entire server on a hunch.

The application isn't being designed as a new media server. Plex, Jellyfin, Emby, Calibre, Audiobookshelf, Kavita, Komga and Navidrome already handle their own areas well enough. This sits alongside them, maintaining the files and portable metadata on which those applications rely. People using no media server at all should still be able to catalogue ordinary folders.

**Current position:** an initial read-only alpha now has a local web dashboard, SQLite catalogue and incremental scanner. There isn't a supported general release yet. Provider matching, server integrations, file renaming and metadata generation remain unimplemented, and the prototype still needs testing on real media servers and large collections.

## A deliberately straightforward interface

The front end should be a local webpage, usable from a desktop or phone on an authorised network. First run needs to be brief: select the types of media in the collection, tick the applications being used, choose the folders and settle on an operating mode. If somebody uses both Plex and Jellyfin, both boxes get ticked. It's not a contest.

Each library should have its own rules. A film directory could be managed automatically after a period of safe, read-only testing, while an existing Calibre library might be inspected without its internal storage ever being touched directly. An audiobook folder may need another naming profile again. The interface should show those differences plainly instead of hiding them under an `Advanced` button and hoping nobody notices.

The main dashboard should answer practical questions: What was scanned? What has changed? What couldn't be identified? Which files need reviewing? Is the background worker still running, and is it behaving itself? It doesn't need to resemble the flight deck of a small aircraft.

## Understanding the media before tidying it

The starting point is discovery. The scanner reads configured folders, examines filenames and useful technical metadata, finds existing sidecars and adds stable references to a local catalogue. ExifTool, FFprobe and MediaInfo are among the tools planned for the job. Expensive analysis should happen only when it can resolve a genuine question.

Identification comes next, and this is where broad filename-cleaning rules tend to make a mess. A series might use broadcast order, DVD order or absolute anime numbering. A film might have more than one cut. Books may have different editions and translators, while music collections can contain several recordings of what looks like the same track. The system needs to keep these distinctions intact and record the evidence behind each match.

Where available and permitted, external providers such as TMDB, TheTVDB, TVmaze, AniList, Open Library, MusicBrainz and subject-specific services can fill in titles, dates, episode identifiers, authors, releases and artwork. They're references, not an excuse to ignore conflicting evidence. If two sources disagree and the existing file doesn't settle the matter, the sensible answer is to ask for a decision and remember it.

Only after identification does renaming become useful. A clean layout ought to make a collection easier to browse and more predictable for media software, but there's no benefit in losing an edition marker, detached subtitle or second language track along the way. Linked files must travel together when a later release gains permission to move them.

## Portable metadata, not one application's private truth

The organiser will maintain its own record of works, editions, individual files, provider identifiers and user corrections. From those records it can generate the sidecars the selected applications understand: NFO for appropriate film and television libraries, OPF for books, ComicInfo.xml for comics, XMP where supported, and JSON for richer reference and provenance data.

The distinction between a work and a physical file matters. Three differently encoded copies of the same film are not three different films; a director's cut isn't necessarily a redundant copy either. The same logic applies to EPUB and PDF editions, RAW photos and edited derivatives, or a studio album and its later remaster. The underlying catalogue should understand these relationships rather than relying on folder names as an improvised database.

Ebooks and suitable reference material should also support Dewey Decimal information where a reliable bibliographic record supplies it. The application won't pretend every item deserves a Dewey number, nor will it manufacture detailed classification from a rough keyword match. It can maintain ordinary subjects, genres and custom tags alongside properly sourced library classifications.

## Quiet operation is a feature, not a setting hidden at the bottom

This application will often sit on a machine already doing other work. Somebody may be watching a film through Plex while Jellyfin scans the same share and a backup runs overnight. The organiser doesn't need to join in by hashing several terabytes at full speed.

The initial design is a single low-priority worker with incremental scanning, stored progress, bounded I/O, job pause/resume and configurable schedules. A file that hasn't changed shouldn't be probed again just because the organiser restarted. Large hashes are mainly for specific integrity and duplicate checks, not everyday discovery. Network shares need more patience than local disks, especially when files are still being copied into place.

Quiet, Balanced and Fast-when-idle profiles should give people meaningful control over resource usage. Actual load will need measuring once there's running code; fictional benchmark numbers look impressive right up until someone uses the software.

## Trust has to be earned

The current prototype scans and reports **without changing a media file**. Later write-capable releases need scoped permissions per library, previews, identity checks, collision detection and a transaction journal. A rename should be recoverable where the filesystem permits it; a cross-filesystem transfer needs a different, more careful procedure. Automatic deletion is out.

An existing NFO or user-corrected title must not be casually replaced by whatever an online provider returns that afternoon. Secrets such as API credentials also need proper storage, not a cosmetic layer of encryption wrapped around a key sitting in the same settings file. LAN access and remote MCP connections should be opt-in, with clear permission boundaries.

This means the application sometimes declines to tidy something automatically. That's not failure; it's the difference between maintaining a library and gambling with it.

## AI as an optional colleague

The media organiser should be capable without a language model. Ordinary filename parsing, metadata queries, classification by verified identifiers, NFO generation, change planning and approved file operations belong in normal application code. Running them through an LLM every time would add cost and uncertainty for little benefit.

Where AI helps is the awkward material: unidentified recordings, misleading titles, unusual subject classifications, badly formatted archives and collections that need a human-style judgement rather than another rigid pattern. An optional MCP server can expose limited read and planning operations to ChatGPT, Claude or other compatible clients. A separate adapter could let a local model assist without sending that material to a remote provider.

Neither type of model should have unrestricted filesystem access. The application should check every operation itself, regardless of who suggested it. A plausible paragraph from a model is not a transaction log.

## Development approach

The initial Linux Python prototype contains a local web GUI, SQLite catalogue, incremental read-only scanner, basic filesystem inspection, job controls and a change report. Docker packaging is still planned. Matching, validated renaming, portable metadata export and consumer integrations follow in separate stages. More media formats, duplicate analysis and optional AI support come once the fundamentals hold up under real tests.

The codebase should be modular without being needlessly elaborate. Media-specific handlers, provider adapters and the file-operation engine each have distinct responsibilities. Tests need to cover the unpleasant cases early: bad filenames, false matches, odd Unicode, broken network mounts, interrupted transfers, duplicate target names and incomplete metadata. Those aren't theoretical edge cases in a real media collection; they're Tuesday.

Comments and development notes will be written in UK English, from the perspective of somebody who actually has to maintain the code. They should say *why* something behaves a particular way, what assumption is being made and what could go wrong. They shouldn't be padded with mechanical explanations of obvious statements, theatrical warnings or needless cheerfulness.

The long-term goal is a small, trustworthy service that can work away in the background and leave a collection in better condition than it found it. If it can be forgotten until there's something genuinely worth reviewing, the design is doing its job.

## Project documents

- [README.md](README.md) — project overview and planned feature set.
- [Product specification](docs/product-spec.md) — intended user flows, formats, integrations and components.
- [Security and safety](docs/security-and-safety.md) — permissions, credentials and file-operation rules.
- [Roadmap](docs/roadmap.md) — the intended sequence of testable development milestones.

This is a public development repository. An open-source licence has not yet been selected, and reference utilities or third-party metadata must only be reused in ways their licences permit.
