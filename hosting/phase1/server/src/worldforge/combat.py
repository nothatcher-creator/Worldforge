from collections import deque
import logging
import time
import uuid

from .rules import ability_turn, grant_xp, roll_item


class Combat:
    def __init__(self, game):
        self.game = game
        self.db = game.db
        self.battles = {}
        self.results = {}

    def for_player(self, cid):
        return next((b for b in self.battles.values() if cid in b["players"]), None)

    def for_monster(self, mid):
        return next((b for b in self.battles.values() if b["monster_id"] == mid), None)

    def enter(self, character, monster_id):
        loc = self.game.world.require_location(character)
        monster = self.db.one("SELECT * FROM monsters WHERE id=?", (monster_id,))
        if not monster or monster["respawn_at"] > time.time() or not self.game.world.nearby(loc, monster, 700):
            raise ValueError("This creature is unavailable or outside your local encounter radius")
        if self.for_player(character["id"]):
            raise ValueError("Already in an encounter")
        party = self.game.party_id(character["id"])
        battle = self.for_monster(monster_id)
        if battle and (not party or party != battle["party_id"]):
            raise ValueError("This encounter belongs to another player or party")
        if not battle:
            definition = self.game.catalog["enemies"][monster["definition_id"]]
            hp = round((definition["base_hp"] + character["level"] * 10) * definition["difficulty"])
            battle = {"id": str(uuid.uuid4()), "monster_id": monster_id, "definition_id": monster["definition_id"],
                      "name": definition["name"], "level": character["level"], "party_id": party,
                      "enemy": {"hp": hp, "max_hp": hp, "wet": 0, "attack": definition["attack"] + character["level"]*2},
                      "players": {}, "turn": 0, "log": deque(maxlen=16)}
            self.battles[battle["id"]] = battle
        if len(battle["players"]) >= 5:
            raise ValueError("Encounter is full")
        stats = self.game.stats(character)
        equipment = self.db.all("SELECT i.legendary_effect FROM equipment e JOIN item_instances i ON e.item_id=i.id WHERE e.character_id=?", (character["id"],))
        stats.update({"id": character["id"], "name": character["name"], "hp": stats["max_hp"], "energy": 10,
                      "guard": 0, "cursor": 0, "cooldowns": {}, "alive": True,
                      "loadout": [r["ability_id"] for r in self.db.all("SELECT ability_id FROM loadout WHERE character_id=? ORDER BY slot", (character["id"],))],
                      "echo_third": any(e["legendary_effect"] == "echo_third" for e in equipment)})
        if battle["players"]:
            # Scale to the strongest participant and group size while preserving
            # damage already dealt. Joining cannot reset encounter progress.
            definition = self.game.catalog["enemies"][battle["definition_id"]]
            battle["level"] = max(battle["level"], character["level"])
            base = (definition["base_hp"] + battle["level"]*10) * definition["difficulty"]
            maximum = round(base * (1 + .55 * len(battle["players"])))
            battle["enemy"]["hp"] += maximum - battle["enemy"]["max_hp"]
            battle["enemy"]["max_hp"] = maximum
            battle["enemy"]["attack"] = definition["attack"] + battle["level"]*2
        battle["players"][character["id"]] = stats
        self.results.pop(character["id"], None)
        return {"battle_id": battle["id"], "message": f"Encounter: {battle['name']}"}

    def retreat(self, cid, message="Retreated safely. Adjust your rotation and try again."):
        battle = self.for_player(cid)
        if not battle:
            raise ValueError("You are not in an encounter")
        del battle["players"][cid]
        self.results[cid] = {"battle_id": battle["id"], "victory": False, "message": message, "at": time.time()}
        if not battle["players"]:
            self.battles.pop(battle["id"], None)
        return {"message": message}

    def tick(self):
        for battle in list(self.battles.values()):
            battle["turn"] += 1
            if battle["turn"] > 120:
                for cid in list(battle["players"]):
                    self.retreat(cid, "Encounter timed out. Try a rotation with more damage.")
                continue
            enemy = battle["enemy"]
            for p in battle["players"].values():
                if not p["alive"]:
                    continue
                p["energy"] = min(10, p["energy"]+1)
                ability_id = p["loadout"][p["cursor"]]
                ability = self.game.catalog["abilities"][ability_id]
                slot = p["cursor"]
                if p["cooldowns"].get(ability_id, 0) > battle["turn"]:
                    result = "cooldown"
                else:
                    result = ability_turn(p, enemy, ability)
                    if result != "rest":
                        p["cooldowns"][ability_id] = battle["turn"] + ability["cooldown"]
                        if slot == 2 and p["echo_third"]:
                            ability_turn(p, enemy, {**ability, "cost": 0})
                battle["log"].append(f"{p['name']} · {ability['name']} ({result})")
                p["cursor"] = (slot+1) % 4
                if enemy["hp"] <= 0:
                    break
            if enemy["hp"] <= 0:
                self.reward(battle)
                del self.battles[battle["id"]]
                continue
            living = [p for p in battle["players"].values() if p["alive"]]
            if living:
                victim = living[(battle["turn"]-1) % len(living)]
                damage = max(1, enemy["attack"] - victim["defence"])
                absorbed = min(damage, victim["guard"])
                victim["guard"] -= absorbed
                victim["hp"] = max(0, victim["hp"] - damage + absorbed)
                victim["alive"] = victim["hp"] > 0
                battle["log"].append(f"{battle['name']} strikes {victim['name']} for {damage-absorbed}")
            enemy["wet"] = max(0, enemy["wet"]-1)
            if not any(p["alive"] for p in battle["players"].values()):
                for cid in battle["players"]:
                    self.results[cid] = {"battle_id": battle["id"], "victory": False, "message": "Retreated to the waycamp. Adjust your rotation and try again.", "at": time.time()}
                del self.battles[battle["id"]]

    def reward(self, battle):
        definition = self.game.catalog["enemies"][battle["definition_id"]]
        for cid in battle["players"]:
            with self.db.transaction() as c:
                if c.execute("SELECT 1 FROM combat_rewards WHERE battle_id=? AND character_id=?", (battle["id"], cid)).fetchone():
                    continue
                character = dict(c.execute("SELECT * FROM characters WHERE id=?", (cid,)).fetchone())
                table = self.game.catalog["loot_tables"][definition["loot_table"]]
                entries = [e for e in table["entries"] if self.game.catalog["items"][e["item_id"]]["required_level"] <= character["level"]]
                rolled, item_id = None, ""
                if entries:
                    key = self.game.rng.choices([e["item_id"] for e in entries], weights=[e["weight"] for e in entries])[0]
                    item_def = self.game.catalog["items"][key]
                    rolled = roll_item(item_def, list(self.game.catalog["affixes"].values()), character["level"], self.game.rng)
                    item_id = self.game.save_item(c, cid, rolled, item_def["version"])
                else:
                    logging.getLogger("worldforge").error("Reward table %s has no eligible equipment at level %s", definition["loot_table"], character["level"])
                xp = definition["xp"] + character["level"] * 2
                gold = definition["gold"]
                level, remainder = grant_xp(character["level"], character["xp"], xp, character["xp_locked"])
                c.execute("UPDATE characters SET gold=gold+?,level=?,xp=? WHERE id=?", (gold, level, remainder, cid))
                c.execute("INSERT INTO combat_rewards VALUES(?,?,?,?,?)", (battle["id"], cid, xp, gold, item_id))
                for quest in self.game.catalog["quests"].values():
                    if quest["type"] == "defeat":
                        c.execute("UPDATE quest_progress SET progress=CASE WHEN progress+1>? THEN ? ELSE progress+1 END WHERE character_id=? AND quest_id=? AND status='active'", (quest["count"], quest["count"], cid, quest["id"]))
                c.execute("UPDATE monsters SET respawn_at=? WHERE id=?", (time.time()+30, battle["monster_id"]))
            self.results[cid] = {"battle_id": battle["id"], "victory": True, "xp": 0 if character["xp_locked"] else xp,
                                 "gold": gold, "item_id": item_id, "item_name": rolled["name"] if rolled else "", "at": time.time(),
                                 "message": f"Victory · {rolled['name'] if rolled else 'No eligible equipment'} · +{gold} gold"}

    def snapshot(self, cid):
        b = self.for_player(cid)
        if not b:
            return None
        return {"id": b["id"], "name": b["name"], "enemy": b["enemy"], "turn": b["turn"], "log": list(b["log"]),
                "participants": [{k: p[k] for k in ("id", "name", "hp", "max_hp", "energy", "cursor", "alive")} for p in b["players"].values()]}
