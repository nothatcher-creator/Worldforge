import math
import time

from .rules import METRES_PER_DEGREE, cell_center, cell_for, distance_m, public_position


class World:
    def __init__(self, game):
        self.game = game
        self.db = game.db

    def region(self, lat, lon):
        for region in self.game.catalog["regions"].values():
            a, b, c, d = region["bounds"]
            if a <= lat <= c and b <= lon <= d:
                return {"id": region["id"], "name": region["name"]}
        return {"id": "fallback", "name": "Uncharted reaches"}

    def update_location(self, character, sample, bypass=False):
        if sample.mock and not self.game.settings.allow_mock_locations:
            raise ValueError("Mock locations are disabled on this server")
        now = time.time()
        old = self.db.one("SELECT * FROM player_locations WHERE character_id=?", (character["id"],))
        inferred_speed = 0
        if old and not bypass:
            elapsed = max(1, now - old["received_at"])
            delta = distance_m(old["lat"], old["lon"], sample.lat, sample.lon)
            jitter = min(500, max(120, old["accuracy"] + sample.accuracy))
            # An offline interval may include a flight. Keep short jumps tightly
            # bounded, then allow plausible aircraft speeds after 15 minutes.
            maximum_speed = 350 if elapsed >= 900 else (85 if elapsed > 60 else 55)
            allowed = jitter + elapsed * maximum_speed
            if delta > allowed:
                with self.db.transaction() as c:
                    c.execute("UPDATE player_locations SET restricted=1 WHERE character_id=?", (character["id"],))
                    c.execute("INSERT INTO location_flags VALUES(?, 'implausible_movement', 1, ?) ON CONFLICT(character_id) DO UPDATE SET reason='implausible_movement',count=location_flags.count+1,updated_at=excluded.updated_at", (character["id"], now))
                raise ValueError("Location jump rejected. Wait for a consistent GPS fix; legitimate arrivals recover after elapsed travel time.")
            if delta > jitter:
                inferred_speed = delta / elapsed
        row, col = cell_for(sample.lat, sample.lon)
        with self.db.transaction() as c:
            c.execute("INSERT INTO player_locations VALUES(?,?,?,?,?,?,?,?,0) ON CONFLICT(character_id) DO UPDATE SET lat=excluded.lat,lon=excluded.lon,accuracy=excluded.accuracy,speed=excluded.speed,cell_lat=excluded.cell_lat,cell_lon=excluded.cell_lon,received_at=excluded.received_at,restricted=0",
                      (character["id"], sample.lat, sample.lon, sample.accuracy, max(sample.speed, inferred_speed), row, col, now))
            if not old:
                c.execute("UPDATE characters SET origin_region=? WHERE id=?", (self.region(sample.lat, sample.lon)["id"], character["id"]))
        self.populate(row, col)
        return {"accepted": True, "region": self.region(sample.lat, sample.lon)}

    def populate(self, row, col):
        center = cell_center(row, col)
        templates = list(self.game.catalog["enemies"])
        with self.db.transaction() as c:
            for i in range(4):
                monster_id = f"{row}:{col}:{i}"
                angle = i * math.pi / 2 + .35
                lat = center["lat"] + math.sin(angle) * 70 / METRES_PER_DEGREE
                lon = center["lon"] + math.cos(angle) * 70 / (METRES_PER_DEGREE * max(.01, math.cos(math.radians(lat))))
                c.execute("INSERT INTO monsters VALUES(?,?,?,?,?,?,0) ON CONFLICT(id) DO NOTHING",
                          (monster_id, templates[i % len(templates)], row, col, lat, lon))

    def require_location(self, character, movement=True):
        loc = self.db.one("SELECT * FROM player_locations WHERE character_id=?", (character["id"],))
        if not loc or time.time() - loc["received_at"] > 120:
            raise ValueError("A fresh foreground GPS fix is required")
        if loc["restricted"]:
            raise ValueError("Geographic actions paused until GPS is consistent")
        if movement and loc["speed"] > 9 and not character["passenger"]:
            raise ValueError("Travel safety mode: gameplay is paused. Passengers may explicitly enable passenger mode.")
        return loc

    def nearby(self, first, second, radius=900):
        return distance_m(first["lat"], first["lon"], second["lat"], second["lon"]) <= radius

    def snapshot(self, character, loc):
        if not loc:
            return {"players": [], "monsters": [], "settlements": [], "camp": None, "region": None}
        blocked = {r["blocked_id"] for r in self.db.all("SELECT blocked_id FROM blocks WHERE blocker_id=?", (character["id"],))}
        blocked |= {r["blocker_id"] for r in self.db.all("SELECT blocker_id FROM blocks WHERE blocked_id=?", (character["id"],))}
        # Candidate lookup uses the spatial index, then exact server-side distance filtering.
        candidates = self.db.all("SELECT c.id,c.name,c.level,l.lat,l.lon FROM player_locations l JOIN characters c ON c.id=l.character_id WHERE l.cell_lat BETWEEN ? AND ? AND l.received_at>? AND c.visible=1 AND c.id!=?",
                                 (loc["cell_lat"]-5, loc["cell_lat"]+5, time.time()-90, character["id"]))
        players = [{"id": r["id"], "name": r["name"], "level": r["level"], "position": public_position(r["lat"], r["lon"]), "precision_m": 300}
                   for r in candidates if r["id"] not in blocked and self.nearby(loc, r)]
        monsters = []
        for r in self.db.all("SELECT * FROM monsters WHERE cell_lat BETWEEN ? AND ?", (loc["cell_lat"]-3, loc["cell_lat"]+3)):
            if self.nearby(loc, r, 700):
                definition = self.game.catalog["enemies"][r["definition_id"]]
                active = self.game.combat.for_monster(r["id"])
                monsters.append({"id": r["id"], "definition_id": r["definition_id"], "name": definition["name"],
                                 "position": {"lat": r["lat"], "lon": r["lon"]}, "available": r["respawn_at"] <= time.time(),
                                 "in_combat": bool(active), "respawn_seconds": max(0, round(r["respawn_at"]-time.time())),
                                 "model_id": definition["model_id"]})
        settlements = []
        for r in self.db.all("SELECT * FROM settlements WHERE lat BETWEEN ? AND ?", (loc["lat"]-.03, loc["lat"]+.03)):
            if self.nearby(loc, r, 1500):
                settlements.append({"id": r["id"], "owner_id": r["owner_id"], "name": r["name"], "level": r["level"],
                                    "capital": True, "position": {"lat": r["lat"], "lon": r["lon"]}})
        return {"players": players[:60], "monsters": monsters[:24], "settlements": settlements[:30],
                "camp": {"id": f"camp:{loc['cell_lat']}:{loc['cell_lon']}", "name": "The Lantern Waycamp", "npc_name": "Keeper Wren",
                         "position": cell_center(loc["cell_lat"], loc["cell_lon"])}, "region": self.region(loc["lat"], loc["lon"])}
