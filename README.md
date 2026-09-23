# WORLDFORGE — v0.4 playable foundation

Worldforge is an Android-first, real-location fantasy RPG/MMO foundation with a server-authoritative multiplayer backend and live server-driven content. Branding remains deliberately replaceable.

## What works now

The original Phase-1 vertical slice remains intact: persistent accounts/characters, GPS world position, a fantasy-tinted real map, deterministic nearby encounters, four-slot auto-battle, randomized affix loot, equipment, XP/levels, quests, privacy-fuzzed nearby players, realtime WebSockets, parties, shared outdoor combat credit, a protected capital, OWNER tools, audit logs and live content publication without an APK rebuild.

The Phase-2 foundation now also includes Mining, Blacksmithing, stackable materials, data-driven recipes, a shared three-room party dungeon, OpenStreetMap/Overpass place ingestion, player trading, persistent settlement buildings, and the new v0.4 town/settlement layer.

### v0.4 additions

- real mapped population centres become interactive fantasy town hubs
- hamlet/village/town/city data drives a 1–4 hub activity scale
- deterministic town NPC rosters grow with the hub scale
- a functional Road Market sells server-defined materials/equipment
- purchases are validated and committed server-side in a transaction
- a functional Wayfarer Inn costs in-game gold and grants three +20% XP victories
- rested XP is private to the rested character and does not leak into party-share XP
- town smithies unlock station-bound recipes
- new `Iron Ingot` and `Smelt Iron Ingot` content demonstrates location/service-gated crafting
- town visits are persisted without counting repeated panel opens as endless visits
- Android town markers are tappable directly on the fantasy map
- Android includes a TOWN browser for nearby mapped population centres
- the capital now has a drag-and-drop settlement plot editor
- existing structures can be moved and rotated without repurchasing them
- new structures are previewed/positioned manually before spending resources
- structures can be removed deliberately with an explicit no-refund warning
- server validates edit ownership, plot bounds and spacing before accepting a layout

## Repository

```text
worldforge/
├── android/
│   └── app/src/main/java/com/worldforge/app/
│       ├── MainActivity.java
│       ├── ApiClient.java
│       ├── SimpleWebSocketClient.java
│       ├── FantasyMapView.java
│       └── SettlementEditorView.java
├── server/
│   ├── src/server.mjs
│   ├── data/seed-content.json
│   └── test/
│       ├── integration.mjs
│       ├── migration.mjs
│       └── poi.mjs
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   └── CONTENT_SCHEMA.md
└── scripts/
```

## Run the backend

Node 22.5+ is required. There are no npm runtime dependencies.

```bash
cd server
npm test
npm start
```

The suite now exercises real two-player presence, parties, combat, quests, randomized loot, settlement creation/build/move/remove, Mining/Blacksmithing, portable and town-station crafting, dungeon summoning/completion, boss materials, player trading, live content publishing, safe POI ingestion, town scaling, vendor/inn services and old-save material migration.

### Development owner

When `WORLDFORGE_DEV_MODE=true`:

- username: `owner`
- password: `worldforge-dev-owner`

Do not expose those development credentials. Shared deployments should use `WORLDFORGE_DEV_MODE=false`, a strong `WORLDFORGE_TOKEN_SECRET`, and explicit owner credentials before first boot.

## Geographic world and towns

`/api/world/places` queries a configurable Overpass endpoint, translates raw OSM data into internal place classes, rejects explicit `access=private`/`access=no` candidates and caches the result by world cell. Population centres retain a small `settlementClass` (`hamlet`, `village`, `town`, `city`) plus population when available.

A nearby population centre can then be opened as `/api/town/hub`. The hub generator is deterministic and server-side, so the Android client does not hard-code a different town for every real location. A rural hamlet remains useful; larger towns/cities simply have more simulated activity/NPC density.

The fallback provider includes a local fantasy hamlet so core service testing/gameplay still works when external geographic data is unavailable.

## Android build

The supplied Android command-line-tools archive installs the SDK manager itself. This sandbox still cannot resolve `dl.google.com`, so it cannot obtain Android platform 36, Build Tools, Gradle or Android Gradle Plugin artifacts for a truthful APK build.

Current target:

- package: `com.worldforge.app`
- version: `0.4.0`
- min SDK: 26
- target/compile SDK: 36
- Java: 17
- Android Gradle Plugin: 8.13.2

On an internet-connected development machine:

```bash
./scripts/install-android-sdk.sh /path/to/commandlinetools-linux-15859902_latest.zip
./scripts/build-android.sh
```

Expected debug APK:

```text
android/app/build/outputs/apk/debug/app-debug.apk
```

The Java sources are syntax-smoke-checked with `javac`. Full Android framework type checking, resource linking, D8 and APK signing still require the missing platform/Gradle artifacts.

## Connect two phones

Run the backend on a computer reachable by both phones. Enter that machine's LAN server URL on each login screen (for example `http://192.168.1.25:8787`), create separate accounts and grant location permission. Nearby players receive viewer-specific privacy-fuzzed map positions.

For any public deployment, use HTTPS/WSS, disable development credentials and remove cleartext HTTP from the Android configuration.

## Town flow

Tap a `T` population-centre marker or open **TOWN**. When physically within the permitted radius, the hub exposes its inn, market, smithy and NPC activity. Resting adds a short-lived server effect; market purchases move only server-owned state; smithy recipes can require the current town ID and fail if used remotely.

## Settlement editor

Open **SETTLE** after founding the protected capital. Choose **PLACE ON PLOT**, drag the preview, rotate it and press **BUILD**. Existing structures can be selected, dragged/rotated and saved. Coordinates remain normalized plot-local values rather than exact residential GPS. Every save is revalidated by the server.

## Authority and privacy

The client never declares gold, XP, loot, crafting results, trade outcomes, town purchases, settlement ownership or combat outcomes. It sends intent; the server validates and commits. Exact GPS remains server-side, nearby strangers receive approximate positions, and public settlement markers are privacy-snapped.

## Next implementation target

The next strong Phase-2 chunk is broader professions and town gameplay: Botany/Fishing/Cooking resource loops, town bulletin-board quest generation, NPC vendors with rotating regional stock, and visitor interaction with player settlements. After that, the existing trade transaction layer can support player vendors/markets.
