# Free hosting preparation — verified 2026-10-02

- SQLite complete suite: **28 passed**, six PostgreSQL-specific checks skipped.
- Real local PostgreSQL 17.6 complete suite: **34 passed**, no skipped checks.
- Both suites retain the existing third-party Starlette/AnyIO deprecation warning.
- Ruff and Git whitespace checks pass.
- Real TCP two-client smoke passes with both database engines: coarse presence,
  parties, shared battle, independent loot, equipment, shared quest credit, live
  publication broadcast and saved data after full process restart.
- Frozen Docker build passes. The production image boots against PostgreSQL
  with the required-PostgreSQL guard, responds to `/health` and runs as UID 10001.
- The free Render blueprint validates against Render's published JSON schema.
  It requests free web compute, no Render disk and no Render database.
- Independent code review found no Critical or Important issue. Additional
  disposable database probes passed: eight simultaneous schema/catalog boots
  produced revision 1, and killing the session immediately before COMMIT caused
  an error without replaying the interrupted insert. These two additional probes
  are not yet retained as permanent regression tests; the main suite already
  tests interruption during a transaction and idle reconnects.

## Deployment still pending

Render and Neon were discovered and offered for connection. The latest check
reports both as uninstalled, so no free resources, source remote or public
server address have been created. Account tier/billing settings and actual
provider HTTPS/WebSocket/restart behavior must be checked once connected.

The existing APK is unchanged. Its physical two-phone acceptance, geographic
map rendering and actual-device performance gates remain open. No Phase 2
features were implemented.
