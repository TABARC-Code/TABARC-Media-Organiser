# Prior art: Ticket Booth

Read on 23 October 2026, from a snapshot of the `main` branch. Ticket Booth is a GTK watchlist app for films and TV, backed by TMDB, written by Alessandro Iepure. It's GPL-3.0-or-later and was archived as end-of-life in April 2026.

It answers a different question from ours: what have I watched, rather than what is on my NAS. But it already does the TMDB lookups and the local SQLite copy, which is the part we're about to build, so it's worth reading.

Nothing from it is copied, pasted or lightly reworded into our code. I read it, closed it, and wrote our own. If this project ever goes GPL that could change, but not before.

## Ideas worth taking

| Idea | What Ticket Booth does | What we'll do | Stage |
|---|---|---|---|
| Language on every lookup | Each TMDB call takes an ISO 639-1 language, defaulting to a user setting | A `provider_language` setting, default `en-GB`, so UK titles win where TMDB has them | 2 |
| Keep both titles | Stores `title`, `original_title` and `original_language` | Same. Match against both, name files from the localised one | 2 |
| Offline flag | A flag that adds a banner and disables adding from TMDB. It's also set automatically when the network drops | `offline = true` in config. Inventory and reports keep working, and providers refuse with a plain message | 2 |
| Refresh schedule | Re-checks TMDB daily, weekly (the default), monthly or never, using a last-update date | A `fetched_at` on each record plus a maximum age. Stale records refresh on demand, not on every run | 2 |
| Flag shifted dates | A `recent_change` flag on titles whose air or release dates moved | Go further: if provider data changes after you approved a match, the match goes back to review instead of being applied quietly | 2 to 3 |
| Manual entries | Titles missing from TMDB can be added by hand with local IDs | Local-only records (home video, obscure releases) as first-class entries, marked `source = manual` | 2 |
| Adult content off | `include_adult=False` on search | Same default, configurable | 2 |
| Whole-catalogue export | One zip holding JSON data and cached images | Export the catalogue, provenance and overrides as JSON, artwork later | 6 |
| Local artwork cache | Posters and backdrops downloaded once and reused | Cache TMDB artwork locally for NFO generation. TheTVDB images stay out, because their terms don't allow them | 4 |

## Traps to avoid

It's a working app that has done its job for years. These are the problems I can see coming.

- Migrations by inspection. New columns are added by checking `PRAGMA table_info` and running `ALTER TABLE` when a name is missing, spread across several functions. There's a `db-needs-update` flag but no schema version. We already store a version and refuse a mismatch. When we need migrations they'll be numbered, one file each, with tests.
- Manual IDs that sort as text. The next ID comes from `ORDER BY id DESC` on strings like `M-9` and `M-10`. As text, `M-9` sorts above `M-10`, so once there are ten manual entries the "next" ID is `M-10` again and collides with the existing one. I ran it in SQLite to confirm. Our manual records use integer keys.
- Paths stored as URI strings and sliced. Image locations are kept as `file://...`, recovered with `[7:]`, and split on the substring `data/`, which also matches a folder called `metadata/`. We store paths relative to a known root.
- Network calls without a timeout. Image downloads use `requests.get(url)` with no timeout, so a stalled connection can hang. Our provider client will have timeouts, retries with backoff and a rate limiter.
- Writes straight to the final file. Downloaded images go directly to their final path, and the cache trusts any file it finds there, so an interrupted download leaves a half-written poster that gets reused. We'll write to a temporary file and rename it.
- Failures with no detail. A failed image download falls back to a blank poster with no log line. Export catches every exception, logs it and returns `False`, so the caller learns that it failed but not why. We record the reason, the way the inventory records scan issues.
- A built-in API key. It can ship a key through the environment, with an option to use your own. We stay with each user's own key, as decided.

## Not relevant to us

The GTK and Adwaita interface, the background activity queue (it keeps a GUI responsive, and we're a CLI), watched and unwatched tracking, release notifications, poster badge colours and Flatpak packaging.
