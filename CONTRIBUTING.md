# Contributing

Author: TABARC-Code

Short version: the tool must never lose or damage someone's library, and it must never pretend to know something it doesn't.

## Ground rules

1. UK English in comments, docs and anything a user sees.
2. Read-only by default. Nothing on disk changes without a saved plan file and an explicit apply command.
3. No deletion of media. Unmatched files and duplicates go to `_review/`. A scan never deletes catalogue rows either, unseen files are marked `present = 0`.
4. Unknown beats wrong. Low-confidence matches go to a review queue, and a missing Dewey class stays blank and labelled unclassified.
5. Every stored value keeps its source, retrieval date and confidence.
6. A provider failure never erases metadata we already hold.
7. If a scan couldn't see part of a root, it marks nothing missing in that root. A silent gap is a bug.

## Providers

Keyless sources come first: Wikidata, TVmaze and Open Library. Each one's licence and attribution is listed in ACKNOWLEDGEMENTS.md. Keyed services (TMDB, TheTVDB) are optional, and each user supplies their own key. Keys are never committed, logged or stored in the catalogue. IMDb datasets are not used. Their terms rule out repackaging.

## Config

- No hard-coded paths.
- Unknown config keys are rejected, not ignored.
- `src/tabarc_media/config/default.toml` and the defaults in `loader.py` must match. A test checks.
- The SQLite catalogue lives on local disk. A database inside a library root is refused.

## Dependencies

Standard library first. Add a package only when the stdlib version would be clearly worse, and say why in the commit.

## Tests

- A stage isn't done until it has tests.
- If a fix guards against a failure, break the guard and confirm the test fails.
- Tests may run as root, so fake permission errors with monkeypatch rather than chmod.
- Never run apply against a live library. Use a copy or the fixtures.

## Exit codes

0 complete. 2 config or catalogue error, or another scan running. 3 complete with issues. 130 interrupted.

## Outside ideas and code

Ideas from other projects get a line in ACKNOWLEDGEMENTS.md. Code from elsewhere needs a compatible licence and its notice kept. See docs/prior-art/ticketbooth.md for how we handled Ticket Booth (GPL, ideas only).
