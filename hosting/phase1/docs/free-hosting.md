# Free multiplayer hosting

Use **Render Free** for the game process and **Neon Free** for PostgreSQL. The
existing APK supports this combination; no Android rebuild is needed. This
delivery prepares hosting, but is not a deployed server until account connections
and the live health/socket tests are complete.

## Connect the services

1. Create free accounts at [Render](https://render.com/) and
   [Neon](https://neon.com/). No paid plan is required.
2. Install/connect the Render and Neon plugins in ChatGPT when offered. Do not
   paste passwords or database connection secrets into chat.
3. Make the project available in a private Git repository accessible to Render.
   The agent can publish the files through the connected GitHub account when a
   suitable source repository is available; otherwise upload the source bundle.

## Deploy

1. Create a **Free** Neon project near Render's region (for the blueprint's
   Virginia region, select an available US East region). Use a dedicated database.
   Keep the free plan and small compute limits; do not enable paid add-ons.
2. Create a Render Blueprint from the repository's [render.yaml](../../../render.yaml).
   Confirm **Free** web compute. It requests no disk and no Render database.
3. Set `WORLDFORGE_DATABASE_URL` privately to the Neon PostgreSQL connection URL.
   The driver verifies TLS and the hostname using system certificate roots.
   `WORLDFORGE_REQUIRE_POSTGRES=1` makes a missing URL fail startup instead of
   silently writing progress into Render's temporary filesystem.
4. Deploy and wait for the `/health` check to pass. Keep exactly **one** runtime
   worker. Render supplies HTTPS and WebSocket ingress to container port 8080.
5. Use the actual `https://…onrender.com` address returned by Render in both
   phones' **Server connection** field. A shared hostname is supported; a dedicated
   IP address is not necessary.

## Owner and backups

An operator with the database secret can run the existing `worldforge.admin
create-owner` command locally against PostgreSQL, with
`WORLDFORGE_DATABASE_URL` set privately in their environment. The command prompts
for the owner's password, creates an OWNER account and writes an audit entry.
Free Render web services have no interactive shell; use the local operator
command or the connected database tools for equivalent audited provisioning.
Never expose a public owner-bootstrap endpoint. Do not import QA accounts/data.

For PostgreSQL exports, use the provider's export tools or `pg_dump`. For example,
set `PGDATABASE` to the connection URL privately, then run:

```sh
pg_dump --format=custom --file=worldforge-backup.dump
```

Keep backup files private. The existing `worldforge.admin backup` command remains
a consistent SQLite backup for local/volume deployments; it explicitly declines
PostgreSQL rather than producing an invalid backup.

## Free plan limits, checked 2026-10-02

- [Render Free](https://render.com/docs/free) pauses a web service after 15 minutes
  without inbound HTTP or WebSocket traffic. The next connection can take about
  one minute to wake it. Its 750 monthly runtime hours are shared by free services
  in the workspace. Local files are erased on sleep/restart/deploy.
- Free Render Postgres expires after 30 days, so this setup uses Neon instead.
- [Neon Free](https://neon.com/pricing) currently provides 1 GB PostgreSQL storage
  and 100 CU-hours per project/month, with no time limit or credit card required.
  It suspends database compute when idle. Stay on the free plan; quotas can pause
  a busy test shard. This is suitable for a small intermittent playtest, not a
  guaranteed always-available MMO.
- Render can charge overages on accounts with a payment method. To preserve the
  user's zero-cost requirement, use a free account without a payment method and
  do not upgrade or enable paid resources. Exhausted allowances should pause the
  service rather than incur charges.

## Acceptance checks

Verify public HTTPS `/health`, two distinct accounts, authenticated WebSockets,
privacy-safe map presence, party combat and inventory. Restart/redeploy the
Render service and verify both accounts' saved progress and content revisions
survive. Complete [the physical two-phone checklist](device-acceptance.md) before
Phase 2, including map rendering and a cellular/Wi-Fi pair.

For local regression checks, set `WORLDFORGE_TEST_POSTGRES` to a local disposable
PostgreSQL URL and run `uv run pytest -q` plus
`uv run python ../scripts/multiplayer_smoke.py` from `server/`. These checks create
and drop only their own random schemas and reject remote database hosts. With
the variable unset, the same commands use SQLite.
