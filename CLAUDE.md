# TABARC Media Organiser — source conventions

You are developing a local-first, safe-by-default media library organiser, not a downloader and not a media server replacement.

**Read before work:** `README.md`, `description.md`, `docs/product-spec.md`, `docs/security-and-safety.md`, `docs/roadmap.md`.

Project-facing documentation must describe the software and its intended users, not its authoring process. Do not mention assistants, model names or automated generation as contributors to the project. AI and MCP may be discussed where they are optional capabilities users can connect to the finished application.

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

## Writing style for code and notes

Write like the programmer responsible for maintaining the code, not like an assistant describing what it has just generated. Use UK English throughout: `organise`, `catalogue`, `behaviour`, `authorise`, `normalise`, `initialise`.

Keep comments where they clarify intent, trade-offs, real failure modes, external API behaviour or non-obvious constraints. An obvious assignment doesn't need a comment. A boundary that prevents a damaged library absolutely does.

Use natural sentence length and paragraph rhythm. Longer explanations are fine when a decision deserves one; a brief inline comment is better when it doesn't. Avoid repetitive headings, template-like sentence fragments, exaggerated certainty, faux enthusiasm, motivational phrases, forced humour and AI-flavoured filler such as "robust and seamless", "elegant solution" or "let's dive in".

A restrained dry observation is fine once in a while, particularly when it describes a genuine technical absurdity. Don't turn code comments into stand-up material or force a percentage of jokes. Prefer candid notes about known limitations to invented personality.

Keep public project descriptions in the project's own voice, without first-person claims about authorship. Source comments should focus on genuine engineering decisions, not the person making them. Explain why a guard exists, what a library assumes, how state is recovered and which cases still need testing. Mark speculation clearly.

**Useful examples:**

```python
# The file may still be growing on a network share. I leave it alone until
# two scans agree on its size and modification time.

# A fast fingerprint narrows down candidates; it doesn't prove the files
# are identical. Full hashes are required before treating a pair as exact.

# Plex and Jellyfin may disagree about episode order. Keep the original
# provider IDs so a later refresh doesn't silently undo a manual correction.
```

**Not useful:**

```python
# First, let's supercharge our powerful media-processing journey!
# Increment the counter by one.
# This magical function flawlessly handles every possible edge case.
```

Write docstrings describing contracts, inputs, outputs, side effects and failure conditions. Add TODOs with a concrete unresolved issue or test case, not vague promises to improve things later. Put architectural decisions in docs rather than dumping essays into source files.

Do not introduce stylistic edits that obscure a security review, and do not rewrite correct existing code just to make the comments sound more human.
