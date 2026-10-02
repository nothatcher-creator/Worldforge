import math
import random


METRES_PER_DEGREE = 111320.0
CELL_METRES = 300.0


def cell_for(lat, lon):
    step = CELL_METRES / METRES_PER_DEGREE
    row = math.floor((lat + 90) / step)
    center_lat = (row + .5) * step - 90
    lon_step = step / max(.01, math.cos(math.radians(center_lat)))
    col = math.floor((lon + 180) / lon_step)
    return row, col


def cell_center(row, col):
    step = CELL_METRES / METRES_PER_DEGREE
    lat = (row + .5) * step - 90
    lon_step = step / max(.01, math.cos(math.radians(lat)))
    lon = (col + .5) * lon_step - 180
    return {"lat": round(lat, 6), "lon": round(min(180, max(-180, lon)), 6)}


def public_position(lat, lon):
    return cell_center(*cell_for(lat, lon))


def distance_m(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    dlat = b - a
    dlon = math.radians(lon2 - lon1)
    h = math.sin(dlat/2)**2 + math.cos(a)*math.cos(b)*math.sin(dlon/2)**2
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


def xp_required(level):
    return round(70 + 20 * level + 2 * level ** 1.45)


def grant_xp(level, xp, amount, locked=False):
    if locked or level >= 120:
        return level, 0 if level >= 120 else xp
    xp += amount
    while level < 120 and xp >= xp_required(level):
        xp -= xp_required(level)
        level += 1
    return level, xp if level < 120 else 0


def roll_item(definition, affixes, level, rng=None):
    rng = rng or random.SystemRandom()
    selected = rng.sample(affixes, definition["affix_count"])
    return {"definition_id": definition["id"], "name": definition["name"], "slot": definition["slot"],
            "rarity": definition["rarity"], "item_level": level,
            "required_level": definition["required_level"], "icon_id": definition["icon_id"],
            "legendary_effect": definition.get("legendary_effect"),
            "base_stats": definition["base_stats"],
            "affixes": [{"id": a["id"], "name": a["name"], "stat": a["stat"],
                          "value": rng.randint(a["min"], a["max"]) + level // 3} for a in selected]}


def ability_turn(player, enemy, ability):
    if player["energy"] < ability["cost"]:
        return "rest"
    player["energy"] -= ability["cost"]
    effect, power = ability["effect"], ability["power"]
    if effect in ("damage", "wet", "arc"):
        damage = power + player["attack"]
        if effect == "arc" and enemy.get("wet", 0) > 0:
            damage = round(damage * 1.5)
        enemy["hp"] = max(0, enemy["hp"] - damage)
        if effect == "wet":
            enemy["wet"] = 5
    elif effect == "guard":
        player["guard"] = power + player.get("defence", 0)
    elif effect == "heal":
        player["hp"] = min(player["max_hp"], player["hp"] + power + player["healing"])
    return effect
