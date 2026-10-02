# Phase 1 multiplayer server

This is the authoritative server for the delivered native Android APK with package `game.worldforge.debug`. It uses the `/v1/` protocol. The existing repository client remains in its original directory.

The root `render.yaml` deploys this folder using **Render Free + Neon Free**. See [setup and limits](docs/free-hosting.md) and [test evidence](docs/free-hosting-verification.md). Accounts and gameplay are stored in PostgreSQL; never use temporary SQLite storage on a free Render service.

Do not enable production mock GPS. Keep one worker. Hosting requires connected accounts and verified public health/WebSocket tests before an address is handed over.
