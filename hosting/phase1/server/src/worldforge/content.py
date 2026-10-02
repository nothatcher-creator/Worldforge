import json
import time

from .config import CONTENT_ROOT
from .schemas import ItemDefinition


class ContentStore:
    def __init__(self, db):
        self.db = db
        seed = json.loads((CONTENT_ROOT / "seed.json").read_text())
        with db.transaction() as c:
            if not c.execute("SELECT 1 FROM content_meta").fetchone():
                c.execute("INSERT INTO content_meta VALUES(1,1)")
                for kind, definitions in seed.items():
                    for key, value in definitions.items():
                        if kind == "items":
                            value = ItemDefinition(**value).model_dump()
                        encoded = json.dumps(value, separators=(",", ":"))
                        c.execute("INSERT INTO content_definitions VALUES(?,?,1,?)", (kind, key, encoded))
                        c.execute("INSERT INTO content_versions VALUES(?,?,1,?,'system',?)",
                                  (kind, key, encoded, time.time()))

    def manifest(self):
        result = {"revision": self.db.one("SELECT revision FROM content_meta WHERE id=1")["revision"]}
        for r in self.db.all("SELECT * FROM content_definitions ORDER BY kind,id"):
            value = json.loads(r["definition"])
            value["version"] = r["version"]
            result.setdefault(r["kind"], {})[r["id"]] = value
        result["brand"] = result["brand"]["default"]
        return result

    def publish_item(self, actor, definition, reason):
        value = definition.model_dump()
        with self.db.transaction() as c:
            others = c.execute("SELECT id,definition FROM content_definitions WHERE kind='items'").fetchall()
            for r in others:
                if r["id"] != definition.id and json.loads(r["definition"])["name"].casefold() == definition.name.casefold():
                    raise ValueError("An item already has this name")
            old = c.execute("SELECT * FROM content_definitions WHERE kind='items' AND id=?", (definition.id,)).fetchone()
            version = old["version"] + 1 if old else 1
            encoded = json.dumps(value, separators=(",", ":"))
            c.execute("INSERT INTO content_definitions VALUES('items',?,?,?) ON CONFLICT(kind,id) DO UPDATE SET version=excluded.version,definition=excluded.definition", (definition.id, version, encoded))
            c.execute("INSERT INTO content_versions VALUES('items',?,?,?,?,?)",
                      (definition.id, version, encoded, actor, time.time()))
            table = c.execute("SELECT * FROM content_definitions WHERE kind='loot_tables' AND id='field'").fetchone()
            if table:
                loot = json.loads(table["definition"])
                loot["entries"] = [e for e in loot["entries"] if e["item_id"] != definition.id]
                if definition.drop_weight:
                    loot["entries"].append({"item_id": definition.id, "weight": definition.drop_weight})
                if not loot["entries"]:
                    raise ValueError("The field reward table must retain at least one item")
                definitions = {r["id"]: json.loads(r["definition"]) for r in c.execute("SELECT id,definition FROM content_definitions WHERE kind='items'")}
                if not any(definitions[e["item_id"]]["required_level"] == 1 for e in loot["entries"]):
                    raise ValueError("The field loot table must retain an eligible starter reward")
                updated = json.dumps(loot, separators=(",", ":"))
                c.execute("UPDATE content_definitions SET version=version+1,definition=? WHERE kind='loot_tables' AND id='field'", (updated,))
                c.execute("INSERT INTO content_versions VALUES('loot_tables','field',?,?,?,?)", (table["version"]+1, updated, actor, time.time()))
                c.execute("INSERT INTO audit_logs(actor,action,timestamp,object_id,old_value,new_value,reason) VALUES(?,?,?,?,?,?,?)",
                          (actor, "loot.source", time.time(), "field", table["definition"], updated, reason))
            c.execute("UPDATE content_meta SET revision=revision+1 WHERE id=1")
            c.execute("INSERT INTO audit_logs(actor,action,timestamp,object_id,old_value,new_value,reason) VALUES(?,?,?,?,?,?,?)",
                      (actor, "item.publish", time.time(), definition.id, old["definition"] if old else None, encoded, reason))
            revision = c.execute("SELECT revision FROM content_meta WHERE id=1").fetchone()[0]
        return {"id": definition.id, "version": version, "revision": revision}

    def history(self):
        result = self.db.all("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100")
        for row in result:
            for key in ("old_value", "new_value"):
                row[key] = json.loads(row[key]) if row[key] else None
        return result

    def versions(self, item_id):
        return self.db.all("SELECT version,actor,created_at FROM content_versions WHERE kind='items' AND id=? ORDER BY version DESC", (item_id,))

    def rollback(self, actor, item_id, version, reason):
        old = self.db.one("SELECT definition FROM content_versions WHERE kind='items' AND id=? AND version=?", (item_id, version))
        if not old:
            raise ValueError("Content version does not exist")
        return self.publish_item(actor, ItemDefinition(**json.loads(old["definition"])), f"Rollback to v{version}: {reason}")
