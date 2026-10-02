import random

import pytest
from pydantic import ValidationError

from worldforge.content import ContentStore
from worldforge.db import Database
from worldforge.rules import ability_turn, distance_m, grant_xp, public_position, roll_item, xp_required
from worldforge.schemas import ItemDefinition


def item(**changes):
    return dict(id="reed_blade", name="Reed blade", description="A flexible original blade.",
                slot="weapon", required_level=1, rarity="rare", base_stats={"attack": 4},
                affix_count=2, icon_id="blade", **changes)


def test_public_location_is_stable_and_coarse():
    a = public_position(45.953, -66.647)
    b = public_position(45.953001, -66.647001)
    assert a == b
    assert a != {"lat": 45.953, "lon": -66.647}
    assert distance_m(45.953, -66.647, a["lat"], a["lon"]) < 220


def test_xp_scales_smoothly_to_120_and_respects_lock():
    assert xp_required(119) / xp_required(118) < 1.03
    assert grant_xp(1, 0, 100, locked=True) == (1, 0)
    assert grant_xp(119, 0, 100000) == (120, 0)
    assert grant_xp(1, 0, xp_required(1)) == (2, 0)


def test_rotation_wet_synergy_guard_and_heal():
    target = {"hp": 100, "wet": 0}
    player = {"hp": 20, "max_hp": 50, "energy": 10, "guard": 0, "attack": 4, "healing": 0}
    ability_turn(player, target, {"effect": "wet", "power": 3, "cost": 1})
    before = target["hp"]
    ability_turn(player, target, {"effect": "arc", "power": 8, "cost": 1})
    assert before - target["hp"] == 18
    ability_turn(player, target, {"effect": "guard", "power": 10, "cost": 1})
    assert player["guard"] == 10
    ability_turn(player, target, {"effect": "heal", "power": 7, "cost": 1})
    assert player["hp"] == 27


def test_unaffordable_ability_is_skipped():
    p = {"hp": 10, "max_hp": 10, "energy": 0, "guard": 0, "attack": 0, "healing": 0}
    e = {"hp": 10, "wet": 0}
    assert ability_turn(p, e, {"effect": "damage", "power": 5, "cost": 2}) == "rest"
    assert e["hp"] == 10


def test_loot_affixes_are_distinct_bounded_and_random():
    definition = ItemDefinition(**item())
    affixes = [dict(id="might", name="Might", stat="attack", min=1, max=3),
               dict(id="shell", name="Shell", stat="defence", min=1, max=3),
               dict(id="heart", name="Heart", stat="max_hp", min=3, max=9)]
    rolls = [roll_item(definition.model_dump(), affixes, 10, random.Random(i)) for i in range(20)]
    assert all(len({a["id"] for a in r["affixes"]}) == 2 for r in rolls)
    assert all(a["value"] <= (9 if a["stat"] == "max_hp" else 3) + 10 for r in rolls for a in r["affixes"])
    assert len({str(r["affixes"]) for r in rolls}) > 1


def test_content_rejects_excess_power_and_unsupported_fields():
    with pytest.raises(ValidationError):
        ItemDefinition(**{**item(), "base_stats": {"attack": 9000}})
    with pytest.raises(ValidationError):
        ItemDefinition(**{**item(), "script": "grant_gold()"})
    with pytest.raises(ValidationError):
        ItemDefinition(**{**item(), "affix_count": 4})


def test_catalog_seed_and_revisions_persist(tmp_path, database_path):
    path = database_path(tmp_path / "world.db")
    db = Database(path)
    store = ContentStore(db)
    first = store.manifest()
    assert len(first["abilities"]) >= 4
    assert first["brand"]["title"] == "Worldforge"
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(id,email,password_hash,role,created_at) VALUES('owner','o@test','x','OWNER',0)")
    result = store.publish_item("owner", ItemDefinition(**item()), "test publish")
    assert result["revision"] > first["revision"]
    assert ContentStore(Database(path)).manifest()["items"]["reed_blade"]["name"] == "Reed blade"
    history = store.history()
    assert history[0]["actor"] == "owner"
    assert history[0]["new_value"]["id"] == "reed_blade"


def test_catalog_duplicate_names_are_rejected(tmp_path, database_path):
    store = ContentStore(Database(database_path(tmp_path / "world.db")))
    store.publish_item("system", ItemDefinition(**item()), "first")
    with pytest.raises(ValueError, match="name"):
        store.publish_item("system", ItemDefinition(**{**item(), "id": "another"}), "duplicate")


def test_published_item_enters_a_versioned_loot_table(tmp_path, database_path):
    store = ContentStore(Database(database_path(tmp_path / "world.db")))
    store.publish_item("system", ItemDefinition(**item()), "Live reward source")
    entries = store.manifest()["loot_tables"]["field"]["entries"]
    assert any(e["item_id"] == "reed_blade" and e["weight"] > 0 for e in entries)
    store.publish_item("system", ItemDefinition(**item()), "Update, no duplicated drop source")
    assert sum(e["item_id"] == "reed_blade" for e in store.manifest()["loot_tables"]["field"]["entries"]) == 1


def test_publication_cannot_remove_all_starter_rewards(tmp_path, database_path):
    store = ContentStore(Database(database_path(tmp_path / "world.db")))
    seed = store.manifest()["items"]
    ids = list(seed)
    for key in ids[:-1]:
        definition = {k:v for k,v in seed[key].items() if k != "version"}
        store.publish_item("system", ItemDefinition(**{**definition, "required_level":120}), "Higher-level reward")
    definition = {k:v for k,v in seed[ids[-1]].items() if k != "version"}
    with pytest.raises(ValueError, match="starter"):
        store.publish_item("system", ItemDefinition(**{**definition,"required_level":120}), "Invalid empty starter pool")
    assert store.manifest()["items"][ids[-1]]["required_level"] == 1
