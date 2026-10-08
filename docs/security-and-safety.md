# Security, secrets and file-operation safety

Status: specification. Security claims must be verified in the implementation.

## Trust boundaries

1. The **local file engine** holds narrowly scoped permission to approved roots, never the whole machine.
2. The **web UI** issues authenticated requests to the engine; a browser does not receive raw API keys.
3. The **provider connector** sends only relevant search terms and IDs to chosen metadata providers.
4. The **AI/MCP bridge** exposes structured, scoped operations with explicit tool grants; LLM output is untrusted.
5. The **server integrations** hold separate limited-scope tokens to media services.

## Network security

Bind to `127.0.0.1` by default. LAN access must be opt-in and protected with authentication, CSRF protections for browser writes, correct origins and TLS via a supported reverse proxy. Do not expose to the public internet by default. Never assume an unauthenticated local port is safe if bound to all interfaces. Do not log secrets, raw session tokens or unrestricted filesystem layouts.

## Credentials

Use the host OS secret store/keyring for native installs when available, or encrypted-at-rest credential storage unlocked with an independent user-provided passphrase (Argon2id-derived key plus authenticated encryption). Container deployments can use Docker secrets or an operator-provided secret mount. The database stores only secret references and non-sensitive key names. Avoid encryption with a key stored alongside ciphertext in the same openly readable config file; that offers negligible protection from local compromise. Never commit keys. Use least-privilege file permissions and allow rotation/revocation.

Full-database encryption is optional and should be documented as separate from API-key encryption; media files themselves are not encrypted by the organiser.

## Write safety policy

- Startup is read-only, and initial release remains entirely read-only.
- User selects distinct policies per root: observe, sidecar-only, managed, staged import, derivative-only.
- Before executing any change, calculate source ID, expected hash/size, current path, target path, associated files, free space, collisions and required permissions.
- Persist a transaction journal: prepared -> authorised -> copying/renaming -> verified -> committed or rolled_back/manual_recovery.
- Same-device rename can be atomic if filesystem permits; cross-device move is verified copy, fsync and explicit commit with source retention until verified. Never claim universal rollback guarantees.
- Prevent path traversal, symlink escapes, arbitrary path access, casefold collisions, reserved filenames, race conditions, TOCTOU and accidental recursive moves.
- Verify affected sidecars/subtitles/extras travel with the media.
- Never auto-delete or overwrite originals. Quarantine is distinct from deletion.
- Document manual restore for every operation class.
- Preserve human edits and original metadata; keep an audit trail of provider changes and override locks.

## AI & MCP

MCP tools accept opaque item/proposal IDs rather than arbitrary file paths. Each privileged operation requires server-side policy verification, current-state checks, a short-lived approval grant and idempotency keys. An AI model cannot elevate its permission by asking in natural language. Avoid prompt injection from filenames, sidecars, metadata descriptions and retrieved provider fields: treat all as untrusted data.

Default MCP availability: search/read-only. Remote connectivity, tunnels and provider sharing are disabled until configured. A visible permissions screen must state which fields may leave the machine.

## Automated test scenarios

Readonly scan causes zero writes under mounted media roots; interrupted transaction; duplicate naming collision; interrupted SMB mount; provider timeout or conflicting matches; malformed XML; symlink escape; delayed file growth; full disk; incorrect filesystem character normalisation; secrets never appear in logs or API responses; unauthorised HTTP writes and replay of approved transactions are rejected.
