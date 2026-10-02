import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


def clean_text(value: str):
    if any(ord(c) < 32 for c in value) or "<" in value or ">" in value:
        raise ValueError("Use plain text without control characters or markup")
    return value.strip()


class Credentials(StrictModel):
    email: str = Field(min_length=5, max_length=180)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email")
        return value


class CharacterInput(StrictModel):
    name: str = Field(min_length=2, max_length=24)

    @field_validator("name")
    @classmethod
    def name_text(cls, v):
        v = clean_text(v)
        if len(v) < 2:
            raise ValueError("Name must have at least two characters")
        return v


class LocationInput(StrictModel):
    lat: float = Field(ge=-85, le=85)
    lon: float = Field(ge=-180, le=180)
    accuracy: float = Field(ge=0, le=10000)
    speed: float = Field(default=0, ge=0, le=400)
    mock: bool = False


class ItemDefinition(StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{2,47}$")
    name: str = Field(min_length=2, max_length=64)
    description: str = Field(max_length=500)
    slot: Literal["weapon", "body", "charm"]
    required_level: int = Field(ge=1, le=120)
    rarity: Literal["common", "uncommon", "rare", "epic", "legendary"]
    base_stats: dict[str, float]
    affix_count: int = Field(ge=1, le=4)
    icon_id: Literal["blade", "tunic", "charm"]
    legendary_effect: Literal["echo_third"] | None = None
    drop_weight: int = Field(default=10, ge=0, le=100)

    @field_validator("name", "description")
    @classmethod
    def text(cls, v):
        return clean_text(v)

    @model_validator(mode="after")
    def budget(self):
        counts = {"common": 1, "uncommon": 1, "rare": 2, "epic": 3, "legendary": 4}
        if self.affix_count != counts[self.rarity]:
            raise ValueError("Affix count must match rarity budget")
        weights = {"attack": 1, "defence": 1.5, "max_hp": .2, "healing": 1.5}
        if not self.base_stats or any(s not in weights for s in self.base_stats):
            raise ValueError("Unsupported base stat")
        if any(not math.isfinite(v) or v < 0 for v in self.base_stats.values()):
            raise ValueError("Stats must be finite and nonnegative")
        if sum(v * weights[s] for s, v in self.base_stats.items()) > 12 + self.required_level * 3:
            raise ValueError("Item exceeds its level stat budget")
        if bool(self.legendary_effect) != (self.rarity == "legendary"):
            raise ValueError("Legendary items require an approved effect; other rarities cannot have one")
        return self


class PublishItem(StrictModel):
    definition: ItemDefinition
    reason: str = Field(default="Live item publication", max_length=240)


class RollbackInput(StrictModel):
    id: str
    version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=240)


class Intent(StrictModel):
    type: Literal["attack", "retreat", "equip", "loadout", "quest_accept", "quest_claim", "gather",
                  "claim_capital", "upgrade_capital", "party_invite", "party_accept", "party_leave",
                  "privacy", "block", "report", "xp_lock", "passenger", "visit", "dev_location"]
    target: str = Field(default="", max_length=100)
    abilities: list[str] | None = Field(default=None, min_length=4, max_length=4)
    value: bool | None = None
    name: str = Field(default="", max_length=32)
    reason: str = Field(default="", max_length=240)
    lat: float | None = Field(default=None, ge=-85, le=85)
    lon: float | None = Field(default=None, ge=-180, le=180)
