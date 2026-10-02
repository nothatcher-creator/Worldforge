import time

import pytest
from fastapi.testclient import TestClient

from worldforge.api import create_app
from worldforge.config import Settings
from worldforge.schemas import Credentials


@pytest.fixture
def client(tmp_path, database_path):
    app = create_app(Settings(database=database_path(tmp_path / "world.db"), development=True,
                              allow_mock_locations=True, tick_seconds=1000))
    with TestClient(app) as c:
        yield c


def player(client, name="Aster"):
    result = client.post("/v1/auth/register", json={"email": f"{name.lower()}@test.example", "password": "testing-only-password"})
    assert result.status_code == 200, result.text
    headers = {"Authorization": f"Bearer {result.json()['token']}"}
    assert client.post("/v1/character", headers=headers, json={"name": name}).status_code == 200
    fix = client.post("/v1/location", headers=headers, json={"lat": 45.953, "lon": -66.647, "accuracy": 8})
    assert fix.status_code == 200, fix.text
    return headers, client.get("/v1/state", headers=headers).json()


def intent(client, headers, kind, **data):
    return client.post("/v1/intent", headers=headers, json={"type": kind, **data})


def finish_battle(client):
    for _ in range(80):
        client.app.state.game.tick()
        if not client.app.state.game.combat.battles:
            return
    pytest.fail("Battle did not finish")


def test_accounts_reject_role_escalation_and_persist_login(client):
    assert client.post("/v1/auth/register", json={"email": "x@test.example", "password": "testing-only-password", "role": "OWNER"}).status_code == 422
    h, state = player(client)
    assert state["self"]["role"] == "PLAYER"
    client.app.state.game.db.close()
    # A new app with the same database simulates a complete process restart.
    with TestClient(create_app(client.app.state.game.settings)) as restarted:
        login = restarted.post("/v1/auth/login", json={"email": "aster@test.example", "password": "testing-only-password"})
        assert login.status_code == 200
        assert restarted.get("/v1/state", headers=h).json()["self"]["id"] == state["self"]["id"]
    # Re-open the connection so the fixture can close cleanly.
    from worldforge.db import Database
    client.app.state.game.db = Database(client.app.state.game.settings.database)


def test_location_privacy_visibility_and_blocking(client):
    a, sa = player(client)
    b, sb = player(client, "Briar")
    peer = client.get("/v1/state", headers=a).json()["world"]["players"][0]
    assert peer["id"] == sb["self"]["id"]
    assert peer["position"] != {"lat": 45.953, "lon": -66.647}
    assert not any(key in peer for key in ("accuracy", "speed", "email", "location"))
    assert intent(client, b, "privacy", value=False).status_code == 200
    assert not client.get("/v1/state", headers=a).json()["world"]["players"]
    intent(client, b, "privacy", value=True)
    assert intent(client, a, "block", target=sb["self"]["id"]).status_code == 200
    assert not client.get("/v1/state", headers=b).json()["world"]["players"]
    assert intent(client, a, "party_invite", target=sb["self"]["id"]).status_code == 400


def test_teleport_is_rejected_and_high_speed_disables_actions(client):
    h, state = player(client)
    bad = client.post("/v1/location", headers=h, json={"lat": 40, "lon": -73, "accuracy": 8})
    assert bad.status_code == 400
    assert client.get("/v1/state", headers=h).json()["self"]["position"]["lat"] == 45.953
    good = client.post("/v1/location", headers=h, json={"lat": 45.953, "lon": -66.647, "accuracy": 8, "speed": 22})
    assert good.status_code == 200
    assert intent(client, h, "attack", target=state["world"]["monsters"][0]["id"]).status_code == 400
    intent(client, h, "passenger", value=True)
    assert intent(client, h, "attack", target=state["world"]["monsters"][0]["id"]).status_code == 200


def test_mock_gps_and_dev_controls_are_server_gated(tmp_path, database_path):
    with TestClient(create_app(Settings(database=database_path(tmp_path / "prod.db"), tick_seconds=1000))) as prod:
        h, _ = player(prod)
        assert prod.post("/v1/location", headers=h, json={"lat": 45.953, "lon": -66.647, "accuracy": 2, "mock": True}).status_code == 400
        assert intent(prod, h, "dev_location", lat=1, lon=1).status_code == 403


def test_offline_flight_arrival_is_accepted_but_impossible_trip_is_rejected(client):
    h, state = player(client)
    cid = state["self"]["id"]
    with client.app.state.game.db.transaction() as c:
        c.execute("UPDATE player_locations SET received_at=? WHERE character_id=?", (time.time()-6*3600, cid))
    # A roughly 5,000 km flight after six offline hours is legitimate travel.
    arrival = {"lat": 48.8566, "lon": 2.3522, "accuracy": 8, "speed": 0}
    response = client.post("/v1/location", headers=h, json=arrival)
    assert response.status_code == 200, response.text
    # A stationary follow-up clears the inferred travel-speed safety gate.
    assert client.post("/v1/location", headers=h, json=arrival).status_code == 200
    assert intent(client, h, "gather", target="botany").status_code == 200
    assert client.get("/v1/state", headers=h).json()["self"]["origin_region"] == state["self"]["origin_region"]
    with client.app.state.game.db.transaction() as c:
        c.execute("UPDATE player_locations SET received_at=? WHERE character_id=?", (time.time()-900, cid))
    impossible = client.post("/v1/location", headers=h, json={"lat": 45.953, "lon": -66.647, "accuracy": 8})
    assert impossible.status_code == 400


def test_authoritative_battle_loot_equipment_and_reward_idempotence(client):
    h, state = player(client)
    target = state["world"]["monsters"][0]["id"]
    assert intent(client, h, "attack", target=target).status_code == 200
    battle = client.app.state.game.combat.battles[next(iter(client.app.state.game.combat.battles))]
    finish_battle(client)
    after = client.get("/v1/state", headers=h).json()["self"]
    assert after["gold"] > 0 and after["xp"] > 0
    assert len(after["inventory"]) == 1 and after["inventory"][0]["affixes"]
    client.app.state.game.combat.reward(battle)
    again = client.get("/v1/state", headers=h).json()["self"]
    assert again["gold"] == after["gold"] and len(again["inventory"]) == 1
    loot = after["inventory"][0]
    assert intent(client, h, "equip", target=loot["id"]).status_code == 200
    assert client.get("/v1/state", headers=h).json()["self"]["equipment"][loot["slot"]] == loot["id"]
    assert intent(client, h, "attack", target=target).status_code == 400


def test_party_invitation_authorization_and_shared_encounter(client):
    a, sa = player(client)
    b, sb = player(client, "Briar")
    c, sc = player(client, "Clover")
    invitation = intent(client, a, "party_invite", target=sb["self"]["id"]).json()["invite_id"]
    assert intent(client, c, "party_accept", target=invitation).status_code == 400
    assert intent(client, b, "party_accept", target=invitation).status_code == 200
    state = client.get("/v1/state", headers=a).json()
    assert len(state["party"]["members"]) == 2
    target = state["world"]["monsters"][0]["id"]
    assert intent(client, a, "attack", target=target).status_code == 200
    assert intent(client, b, "attack", target=target).status_code == 200
    assert intent(client, c, "attack", target=target).status_code == 400
    finish_battle(client)
    for headers in (a, b):
        s = client.get("/v1/state", headers=headers).json()
        assert len(s["self"]["inventory"]) == 1
        assert s["self"]["gold"] > 0


def test_quest_claim_is_once_and_profession_capital_persist(client):
    h, state = player(client)
    assert intent(client, h, "quest_accept", target="camp_hunt").status_code == 200
    for i in range(3):
        state = client.get("/v1/state", headers=h).json()
        target = next(m["id"] for m in state["world"]["monsters"] if m["available"])
        assert intent(client, h, "attack", target=target).status_code == 200
        finish_battle(client)
    assert intent(client, h, "quest_claim", target="camp_hunt").status_code == 200
    assert intent(client, h, "quest_claim", target="camp_hunt").status_code == 400
    assert intent(client, h, "gather", target="botany").status_code == 200
    assert intent(client, h, "gather", target="botany").status_code == 400
    assert intent(client, h, "claim_capital", name="Moss lantern").status_code == 200
    assert intent(client, h, "claim_capital", name="Second capital").status_code == 400
    s = client.get("/v1/state", headers=h).json()["self"]
    assert s["capital"]["capital"] == 1
    assert s["skills"][0]["xp"] == 10
    assert s["resources"][0]["quantity"] >= 1


def test_four_slots_validate_and_xp_lock(client):
    h, _ = player(client)
    assert intent(client, h, "loadout", abilities=["rill", "arc", "mend"]).status_code == 422
    assert intent(client, h, "loadout", abilities=["rill", "hack", "mend", "ward"]).status_code == 400
    assert intent(client, h, "loadout", abilities=["mend", "ward", "rill", "arc"]).status_code == 200
    intent(client, h, "xp_lock", value=True)
    s = client.get("/v1/state", headers=h).json()
    intent(client, h, "attack", target=s["world"]["monsters"][0]["id"])
    finish_battle(client)
    assert client.get("/v1/state", headers=h).json()["self"]["xp"] == 0


def test_live_content_rbac_broadcast_audit_and_rollback(client):
    h, _ = player(client)
    owner = client.app.state.game.register(Credentials(email="owner@test.example", password="testing-owner-password"), role="OWNER")
    oh = {"Authorization": f"Bearer {owner['token']}"}
    definition = dict(id="new_sword", name="New original sword", description="Live catalog proof", slot="weapon",
                      required_level=1, rarity="rare", base_stats={"attack": 6}, affix_count=2, icon_id="blade")
    assert client.post("/v1/admin/items", headers=h, json={"definition": definition}).status_code == 403
    token = h["Authorization"].split(" ")[1]
    with client.websocket_connect("/v1/live") as ws:
        ws.send_json({"type": "auth", "token": token})
        assert ws.receive_json()["type"] == "snapshot"
        published = client.post("/v1/admin/items", headers=oh, json={"definition": definition})
        assert published.status_code == 200, published.text
        event = ws.receive_json()
        assert event["type"] == "content_changed"
        assert event["revision"] == published.json()["revision"]
    catalog = client.get("/v1/content").json()
    assert catalog["items"]["new_sword"]["name"] == definition["name"]
    assert client.get("/v1/admin/history", headers=oh).json()[0]["action"] == "item.publish"
    definition["name"] = "Revised sword"
    client.post("/v1/admin/items", headers=oh, json={"definition": definition})
    rollback = client.post("/v1/admin/rollback", headers=oh, json={"id": "new_sword", "version": 1, "reason": "Restore approved name"})
    assert rollback.status_code == 200
    assert client.get("/v1/content").json()["items"]["new_sword"]["version"] == 3
    assert client.get("/v1/content").json()["items"]["new_sword"]["name"] == "New original sword"


def test_expired_session_and_websocket_auth(client):
    h, _ = player(client)
    with client.app.state.game.db.transaction() as c:
        c.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
    assert client.get("/v1/state", headers=h).status_code == 401
    with client.websocket_connect("/v1/live") as ws:
        ws.send_json({"type": "auth", "token": "invalid"})
        with pytest.raises(Exception):
            ws.receive_json()


def test_client_cannot_submit_rewards_or_currency(client):
    h, _ = player(client)
    assert client.post("/v1/intent", headers=h, json={"type": "attack", "gold": 9000, "xp": 9000}).status_code == 422
    assert client.post("/v1/intent", headers=h, json={"type": "grant_gold", "value": True}).status_code == 422


def test_defensive_rotation_times_out_without_reward_and_can_retreat(client):
    h, state = player(client)
    assert intent(client, h, "loadout", abilities=["ward"]*4).status_code == 200
    target = state["world"]["monsters"][0]["id"]
    intent(client, h, "attack", target=target)
    for _ in range(121):
        client.app.state.game.tick()
    state = client.get("/v1/state", headers=h).json()
    assert state["battle"] is None
    assert state["last_result"]["victory"] is False
    assert state["self"]["gold"] == 0
    assert intent(client, h, "attack", target=target).status_code == 200
    assert intent(client, h, "retreat").status_code == 200
    assert client.get("/v1/state", headers=h).json()["battle"] is None


def test_old_solo_invite_cannot_join_another_leaders_party(client):
    a, sa = player(client)
    b, sb = player(client, "Briar")
    d, sd = player(client, "Dusk")
    old = intent(client, a, "party_invite", target=sb["self"]["id"]).json()["invite_id"]
    other = intent(client, d, "party_invite", target=sa["self"]["id"]).json()["invite_id"]
    assert intent(client, a, "party_accept", target=other).status_code == 200
    assert intent(client, b, "party_accept", target=old).status_code == 400
    assert len(client.get("/v1/state", headers=d).json()["party"]["members"]) == 2


def test_party_enemy_scales_to_highest_joined_character(client):
    a, sa = player(client)
    b, sb = player(client, "Briar")
    invitation = intent(client, a, "party_invite", target=sb["self"]["id"]).json()["invite_id"]
    intent(client, b, "party_accept", target=invitation)
    with client.app.state.game.db.transaction() as conn:
        conn.execute("UPDATE characters SET level=20 WHERE id=?", (sb["self"]["id"],))
    target = sa["world"]["monsters"][0]["id"]
    intent(client, a, "attack", target=target)
    before = client.get("/v1/state", headers=a).json()["battle"]["enemy"]["max_hp"]
    intent(client, b, "attack", target=target)
    after = client.get("/v1/state", headers=a).json()["battle"]["enemy"]
    assert after["max_hp"] > before * 3
    assert after["attack"] >= 40
