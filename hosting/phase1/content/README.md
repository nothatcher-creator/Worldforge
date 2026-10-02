# Content and identity

`seed.json` is the original initial catalog. A new database installs every entry as version 1; a running database is authoritative afterwards. IDs must remain stable when display names change.

Brand title/subtitle/colors live in `brand.default`. Android launch labels and launcher icon live under `android/app/src/main/res`; theme fallbacks are in `Theme.kt`. Map presentation is `fantasy-style.json`; its packaged copy is `android/app/src/main/assets/fantasy-style.json`. Primitive original map silhouettes live in `FantasyMap.kt:markerArt`, behind stable asset keys. Replace those renderers or artwork without touching combat rules. MapLibre/OpenStreetMap attribution must remain even when game branding changes.

The manifest groups definitions into brand, assets, abilities, affixes, items, loot_tables, enemies, quests, professions, buildings and regions. Every definition has an individual version, and the entire manifest has a monotonically increasing revision. Clients cache it privately and refresh upon a `content_changed` WebSocket event or a newer snapshot revision.

The item editor supports three equipment slots, five rarities, 1–4 controlled affixes, level 1–120 and four base stats. Weighted base-stat budget is `12 + 3 × required_level`: attack weight 1, defence/healing weight 1.5, health weight .2. Legendary effects use the approved `echo_third` opcode. `drop_weight` defaults to 10 and ranges 0–100 in the API; 0 removes the item from the field reward source. Live publications may not remove every eligible level-1 reward. Field enemy loot uses these weights plus level eligibility. No text becomes executable code.

Affixes roll without replacement from approved stats. Rolled values, item level, name, icon and definition version are saved per instance. Subsequent catalog edits affect new rolls. Per-instance equipment values never come from the client.

Abilities use closed generic effects: damage, wet, arc, guard and heal. Client UI renders names, descriptions, colors and costs from definitions. A fundamentally new renderer or mechanic still requires client/server code; live content does not mean arbitrary code execution. A future editor can submit another validated definition kind through the same revision/audit architecture. Human-reviewed content is the only authoring path in this phase.

The one hunt is an original reusable defeat objective, with target count, level floor and currency/XP rewards. The server can credit any eligible active hunt to each participant. Town POIs, full geographic access filtering, regional cultures, factions, secret discoveries and broader quest objective evaluators remain in later phases.
