import random
import threading
import time
import uuid

from .combat import Combat
from .content import ContentStore
from .db import Database, INTEGRITY_ERRORS
from .rules import grant_xp, public_position, xp_required
from .schemas import LocationInput, clean_text
from .security import hash_password, new_token, token_hash, verify_password
from .world import World


class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


class Game:
    def __init__(self, settings):
        self.settings = settings
        self.db = Database(settings.database)
        self.content = ContentStore(self.db)
        self.catalog = self.content.manifest()
        self.lock = threading.RLock()
        self.rng = random.SystemRandom()
        self.world = World(self)
        self.combat = Combat(self)

    def register(self, credentials, role="PLAYER"):
        uid = str(uuid.uuid4())
        password_hash = hash_password(credentials.password)
        try:
            with self.db.transaction() as c:
                c.execute("INSERT INTO users VALUES(?,?,?,?,?)", (uid, credentials.email, password_hash, role, time.time()))
        except INTEGRITY_ERRORS:
            raise ValueError("An account with this email already exists") from None
        return self.session(uid)

    def login(self, credentials):
        user = self.db.one("SELECT * FROM users WHERE email=?", (credentials.email,))
        # A fixed dummy hash prevents user-existence timing from skipping scrypt entirely.
        encoded = user["password_hash"] if user else "scrypt$00000000000000000000000000000000$" + "0"*128
        if not verify_password(credentials.password, encoded) or not user:
            raise Unauthorized("Email or password is incorrect")
        return self.session(user["id"])

    def session(self, uid):
        token = new_token()
        with self.db.transaction() as c:
            c.execute("DELETE FROM sessions WHERE expires_at<?", (time.time(),))
            c.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), uid, time.time()+self.settings.session_days*86400))
        user = self.db.one("SELECT id,role FROM users WHERE id=?", (uid,))
        return {"token": token, "user": user, "has_character": bool(self.character(uid, required=False))}

    def authenticate(self, token):
        user = self.db.one("SELECT u.id,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>?", (token_hash(token), time.time()))
        if not user:
            raise Unauthorized("Session expired. Please sign in again.")
        return user

    def character(self, uid, required=True):
        result = self.db.one("SELECT * FROM characters WHERE user_id=?", (uid,))
        if required and not result:
            raise ValueError("Create a character first")
        return result

    def create_character(self, uid, data):
        with self.lock:
            if self.character(uid, required=False):
                raise ValueError("This account already has a character")
            cid = str(uuid.uuid4())
            with self.db.transaction() as c:
                c.execute("INSERT INTO characters(id,user_id,name,origin_region,created_at) VALUES(?,?,?,'fallback',?)", (cid, uid, data.name, time.time()))
                for i, ability in enumerate(("rill", "arc", "ward", "mend")):
                    c.execute("INSERT INTO loadout VALUES(?,?,?)", (cid, i, ability))
                c.execute("INSERT INTO skills(character_id,skill_id) VALUES(?,'botany')", (cid,))
            return self.snapshot(uid)

    def update_location(self, uid, sample):
        with self.lock:
            return self.world.update_location(self.character(uid), sample)

    def stats(self, character):
        stats = {"attack": 3+character["level"]*2, "defence": 2+character["level"],
                 "max_hp": 60+character["level"]*12, "healing": character["level"]}
        for row in self.db.all("SELECT s.stat,s.value FROM equipment e JOIN item_stats s ON s.item_id=e.item_id WHERE e.character_id=? UNION ALL SELECT a.stat,a.value FROM equipment e JOIN item_affixes a ON a.item_id=e.item_id WHERE e.character_id=?", (character["id"], character["id"])):
            stats[row["stat"]] += row["value"]
        return stats

    def save_item(self, c, cid, rolled, version):
        iid = str(uuid.uuid4())
        c.execute("INSERT INTO item_instances VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (iid, cid, rolled["definition_id"], version, rolled["name"], rolled["slot"], rolled["rarity"],
                   rolled["item_level"], rolled["required_level"], rolled["icon_id"], rolled.get("legendary_effect"), time.time()))
        for stat, value in rolled["base_stats"].items():
            c.execute("INSERT INTO item_stats VALUES(?,?,?)", (iid, stat, value))
        for affix in rolled["affixes"]:
            c.execute("INSERT INTO item_affixes VALUES(?,?,?,?,?)", (iid, affix["id"], affix["name"], affix["stat"], affix["value"]))
        return iid

    def inventory(self, cid):
        items = self.db.all("SELECT * FROM item_instances WHERE character_id=? ORDER BY created_at DESC LIMIT 500", (cid,))
        for item in items:
            item["base_stats"] = {r["stat"]: r["value"] for r in self.db.all("SELECT stat,value FROM item_stats WHERE item_id=?", (item["id"],))}
            item["affixes"] = self.db.all("SELECT affix_id AS id,name,stat,value FROM item_affixes WHERE item_id=?", (item["id"],))
            del item["character_id"]
        return items

    def party_id(self, cid):
        member = self.db.one("SELECT party_id FROM party_members WHERE character_id=?", (cid,))
        return member["party_id"] if member else None

    def party_snapshot(self, cid):
        pid = self.party_id(cid)
        if not pid:
            return None
        party = self.db.one("SELECT * FROM parties WHERE id=?", (pid,))
        members = self.db.all("SELECT c.id,c.name,c.level FROM party_members p JOIN characters c ON c.id=p.character_id WHERE p.party_id=?", (pid,))
        for member in members:
            battle = self.combat.for_player(member["id"])
            p = battle["players"][member["id"]] if battle else None
            member["hp"] = p["hp"] if p else None
            member["max_hp"] = p["max_hp"] if p else None
            loc = self.db.one("SELECT received_at FROM player_locations WHERE character_id=?", (member["id"],))
            member["online"] = bool(loc and time.time()-loc["received_at"] < 90)
        return {**party, "members": members}

    def snapshot(self, uid):
        with self.lock:
            character = self.character(uid, required=False)
            if not character:
                return {"self": None, "content_revision": self.catalog["revision"], "development": self.settings.development}
            cid = character["id"]
            location = self.db.one("SELECT * FROM player_locations WHERE character_id=?", (cid,))
            user = self.db.one("SELECT role FROM users WHERE id=?", (uid,))
            self_state = {k: character[k] for k in ("id", "name", "level", "xp", "gold", "xp_locked", "visible", "passenger", "origin_region")}
            self_state.update({"role": user["role"], "xp_next": xp_required(character["level"]), "stats": self.stats(character),
                               "position": {"lat": location["lat"], "lon": location["lon"]} if location else None,
                               "location_fresh": bool(location and time.time()-location["received_at"] < 120),
                               "movement_locked": bool(location and (location["restricted"] or (location["speed"]>9 and not character["passenger"]))),
                               "loadout": [r["ability_id"] for r in self.db.all("SELECT ability_id FROM loadout WHERE character_id=? ORDER BY slot", (cid,))],
                               "inventory": self.inventory(cid),
                               "equipment": {r["slot"]: r["item_id"] for r in self.db.all("SELECT * FROM equipment WHERE character_id=?", (cid,))},
                               "quests": self.db.all("SELECT quest_id,progress,status FROM quest_progress WHERE character_id=?", (cid,)),
                               "skills": self.db.all("SELECT skill_id,xp,next_action_at FROM skills WHERE character_id=?", (cid,)),
                               "resources": self.db.all("SELECT resource_id,quantity FROM resources WHERE character_id=?", (cid,)),
                               "capital": self.db.one("SELECT * FROM settlements WHERE owner_id=?", (cid,))})
            return {"self": self_state, "world": self.world.snapshot(character, location), "party": self.party_snapshot(cid),
                    "invites": self.db.all("SELECT i.id,c.name AS sender_name FROM party_invites i JOIN characters c ON c.id=i.sender_id WHERE i.target_id=? AND i.expires_at>?", (cid, time.time())),
                    "battle": self.combat.snapshot(cid), "last_result": self.combat.results.get(cid),
                    "content_revision": self.catalog["revision"], "development": self.settings.development, "server_time": time.time()}

    def tick(self):
        with self.lock:
            self.combat.tick()
            now = time.time()
            self.combat.results = {cid: r for cid, r in self.combat.results.items() if now-r["at"] < 300}
            with self.db.transaction() as c:
                c.execute("DELETE FROM party_invites WHERE expires_at<?", (now,))

    def intent(self, uid, data):
        with self.lock:
            character = self.character(uid)
            cid, kind = character["id"], data.type
            if kind == "dev_location":
                user = self.db.one("SELECT role FROM users WHERE id=?", (uid,))
                if user["role"] != "OWNER" or not self.settings.allow_mock_locations:
                    raise Forbidden("Owner mock GPS requires a development server with explicit mock-location support")
                if data.lat is None or data.lon is None:
                    raise ValueError("Coordinates required")
                result = self.world.update_location(character, LocationInput(lat=data.lat, lon=data.lon, accuracy=1, mock=True), bypass=True)
                with self.db.transaction() as c:
                    c.execute("INSERT INTO audit_logs(actor,action,timestamp,object_id,reason) VALUES(?,?,?,?,?)", (uid, "dev.mock_location", time.time(), cid, "Development location override"))
                return result
            if kind in ("attack", "gather", "claim_capital", "visit", "quest_accept", "quest_claim"):
                self.world.require_location(character)
            if kind == "attack":
                return self.combat.enter(character, data.target)
            if kind == "retreat":
                return self.combat.retreat(cid)
            if kind == "equip":
                if self.combat.for_player(cid):
                    raise ValueError("Change equipment between encounters")
                item = self.db.one("SELECT * FROM item_instances WHERE id=? AND character_id=?", (data.target, cid))
                if not item or item["required_level"] > character["level"]:
                    raise ValueError("Item not owned or requires a higher level")
                with self.db.transaction() as c:
                    c.execute("INSERT INTO equipment VALUES(?,?,?) ON CONFLICT(character_id,slot) DO UPDATE SET item_id=excluded.item_id", (cid, item["slot"], item["id"]))
                return {"message": f"Equipped {item['name']}"}
            if kind == "loadout":
                if self.combat.for_player(cid):
                    raise ValueError("Change abilities between encounters")
                if not data.abilities or any(key not in self.catalog["abilities"] for key in data.abilities):
                    raise ValueError("Choose four known abilities")
                with self.db.transaction() as c:
                    for i, ability in enumerate(data.abilities):
                        c.execute("UPDATE loadout SET ability_id=? WHERE character_id=? AND slot=?", (ability, cid, i))
                return {"message": "Rotation saved"}
            if kind in ("xp_lock", "privacy", "passenger"):
                if data.value is None:
                    raise ValueError("A boolean preference is required")
                column = {"xp_lock": "xp_locked", "privacy": "visible", "passenger": "passenger"}[kind]
                with self.db.transaction() as c:
                    c.execute(f"UPDATE characters SET {column}=? WHERE id=?", (int(data.value), cid))
                return {"message": "Preference saved"}
            if kind.startswith("quest_"):
                quest = self.catalog["quests"].get(data.target)
                if not quest or character["level"] < quest["minimum_level"]:
                    raise ValueError("Quest unavailable")
                with self.db.transaction() as c:
                    existing = c.execute("SELECT * FROM quest_progress WHERE character_id=? AND quest_id=?", (cid, data.target)).fetchone()
                    if kind == "quest_accept":
                        if existing:
                            raise ValueError("Quest already accepted or completed")
                        c.execute("INSERT INTO quest_progress(character_id,quest_id) VALUES(?,?)", (cid, data.target))
                    else:
                        if not existing or existing["status"] != "active" or existing["progress"] < quest["count"]:
                            raise ValueError("Quest is not ready for a reward")
                        level, xp = grant_xp(character["level"], character["xp"], quest["reward_xp"], character["xp_locked"])
                        c.execute("UPDATE characters SET level=?,xp=?,gold=gold+? WHERE id=?", (level, xp, quest["reward_gold"], cid))
                        c.execute("UPDATE quest_progress SET status='claimed' WHERE character_id=? AND quest_id=?", (cid, data.target))
                return {"message": "Quest accepted" if kind == "quest_accept" else "Quest reward received"}
            if kind == "gather":
                profession = self.catalog["professions"].get(data.target)
                if not profession:
                    raise ValueError("Unknown profession")
                quantity = self.rng.randint(1, 3)
                with self.db.transaction() as c:
                    skill = c.execute("SELECT * FROM skills WHERE character_id=? AND skill_id=?", (cid, data.target)).fetchone()
                    if not skill or skill["next_action_at"] > time.time():
                        raise ValueError("This resource is recovering; try again shortly")
                    c.execute("UPDATE skills SET xp=xp+?,next_action_at=? WHERE character_id=? AND skill_id=?", (profession["xp"], time.time()+profession["cooldown_seconds"], cid, data.target))
                    c.execute("INSERT INTO resources VALUES(?,?,?) ON CONFLICT(character_id,resource_id) DO UPDATE SET quantity=resources.quantity+excluded.quantity", (cid, profession["resource_id"], quantity))
                return {"message": f"Gathered {quantity} {profession['resource_name']} · +{profession['xp']} skill XP"}
            if kind in ("claim_capital", "upgrade_capital"):
                capital = self.db.one("SELECT * FROM settlements WHERE owner_id=?", (cid,))
                rules = self.catalog["buildings"]["capital"]
                cost = rules["claim_cost"] if kind == "claim_capital" else rules["upgrade_cost"]*(capital["level"] if capital else 1)
                if character["gold"] < cost:
                    raise ValueError(f"Requires {cost} earned gold")
                if kind == "claim_capital" and capital:
                    raise ValueError("You already have a protected capital")
                if kind == "upgrade_capital" and not capital:
                    raise ValueError("Claim a capital first")
                name = clean_text(data.name or f"{character['name']}'s Lanternstead")
                with self.db.transaction() as c:
                    c.execute("UPDATE characters SET gold=gold-? WHERE id=?", (cost, cid))
                    if kind == "claim_capital":
                        loc = self.world.require_location(character)
                        pos = public_position(loc["lat"], loc["lon"])
                        c.execute("INSERT INTO settlements VALUES(?,?,?,?,?,1,1,?)", (str(uuid.uuid4()), cid, name, pos["lat"], pos["lon"], time.time()))
                    else:
                        c.execute("UPDATE settlements SET level=level+1 WHERE owner_id=?", (cid,))
                return {"message": "Protected capital established" if kind == "claim_capital" else "Capital upgraded"}
            if kind == "party_invite":
                loc = self.world.require_location(character)
                other = self.db.one("SELECT * FROM characters WHERE id=?", (data.target,))
                blocked = self.db.one("SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)", (cid, data.target, data.target, cid))
                if not other or other["id"] == cid or blocked or not other["visible"]:
                    raise ValueError("Player unavailable for invitations")
                other_loc = self.world.require_location(other, movement=False)
                if not self.world.nearby(loc, other_loc) or self.party_id(other["id"]):
                    raise ValueError("Player is outside the local area or already in a party")
                pid = self.party_id(cid)
                if pid:
                    party = self.db.one("SELECT * FROM parties WHERE id=?", (pid,))
                    if party["leader_id"] != cid or len(self.party_snapshot(cid)["members"]) >= 5:
                        raise ValueError("Only a leader with a free party slot may invite")
                iid = str(uuid.uuid4())
                with self.db.transaction() as c:
                    c.execute("DELETE FROM party_invites WHERE sender_id=? AND target_id=?", (cid, data.target))
                    c.execute("INSERT INTO party_invites VALUES(?,?,?,?)", (iid, cid, data.target, time.time()+120))
                return {"invite_id": iid, "message": "Party invitation sent"}
            if kind == "party_accept":
                invitation = self.db.one("SELECT * FROM party_invites WHERE id=? AND target_id=? AND expires_at>?", (data.target, cid, time.time()))
                if not invitation or self.party_id(cid):
                    raise ValueError("Invitation expired, unavailable, or already in a party")
                sender = invitation["sender_id"]
                blocked = self.db.one("SELECT 1 FROM blocks WHERE (blocker_id=? AND blocked_id=?) OR (blocker_id=? AND blocked_id=?)", (cid, sender, sender, cid))
                if blocked:
                    raise ValueError("Invitation blocked")
                pid = self.party_id(sender)
                if pid and self.db.one("SELECT leader_id FROM parties WHERE id=?", (pid,))["leader_id"] != sender:
                    raise ValueError("The sender no longer has permission to invite you")
                if pid and len(self.party_snapshot(sender)["members"]) >= 5:
                    raise ValueError("Party is full")
                with self.db.transaction() as c:
                    if not pid:
                        pid = str(uuid.uuid4())
                        c.execute("INSERT INTO parties VALUES(?,?)", (pid, sender))
                        c.execute("INSERT INTO party_members VALUES(?,?)", (pid, sender))
                    c.execute("INSERT INTO party_members VALUES(?,?)", (pid, cid))
                    # Membership changes invalidate outgoing invitations. They must
                    # never be silently redirected into another leader's party.
                    c.execute("DELETE FROM party_invites WHERE target_id=? OR sender_id=?", (cid, cid))
                return {"message": "Joined party. Tap your friend's encounter to fight together."}
            if kind == "party_leave":
                if self.combat.for_player(cid):
                    raise ValueError("Leave the party between encounters")
                pid = self.party_id(cid)
                if not pid:
                    raise ValueError("Not in a party")
                with self.db.transaction() as c:
                    c.execute("DELETE FROM party_members WHERE character_id=?", (cid,))
                    c.execute("DELETE FROM party_invites WHERE sender_id=?", (cid,))
                    members = c.execute("SELECT character_id FROM party_members WHERE party_id=?", (pid,)).fetchall()
                    if not members:
                        c.execute("DELETE FROM parties WHERE id=?", (pid,))
                    else:
                        c.execute("UPDATE parties SET leader_id=? WHERE id=? AND leader_id=?", (members[0][0], pid, cid))
                return {"message": "Left party"}
            if kind in ("block", "report"):
                if data.target == cid or not self.db.one("SELECT id FROM characters WHERE id=?", (data.target,)):
                    raise ValueError("Unknown player")
                with self.db.transaction() as c:
                    if kind == "block":
                        c.execute("INSERT INTO blocks VALUES(?,?) ON CONFLICT(blocker_id,blocked_id) DO NOTHING", (cid, data.target))
                        c.execute("DELETE FROM party_invites WHERE (sender_id=? AND target_id=?) OR (sender_id=? AND target_id=?)", (cid, data.target, data.target, cid))
                    else:
                        if len(data.reason.strip()) < 3:
                            raise ValueError("Describe the report reason")
                        c.execute("INSERT INTO reports VALUES(?,?,?,?,?)", (str(uuid.uuid4()), cid, data.target, clean_text(data.reason), time.time()))
                return {"message": "Player blocked" if kind == "block" else "Report saved for staff review"}
            if kind == "visit":
                loc = self.world.require_location(character)
                if data.target.startswith("camp:"):
                    return {"message": "Welcome to the local waycamp. Wren offers the local hunt and a place to gather."}
                capital = self.db.one("SELECT * FROM settlements WHERE id=?", (data.target,))
                if not capital or not self.world.nearby(loc, capital, 1500):
                    raise ValueError("Settlement is outside your local area")
                return {"message": f"Visiting {capital['name']} · level {capital['level']} protected capital", "settlement": capital}
            raise ValueError("Unsupported intention")
