from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: str = "worldforge.db"
    development: bool = False
    allow_mock_locations: bool = False
    tick_seconds: float = 1.0
    session_days: int = 30

    @classmethod
    def from_env(cls):
        dev = os.getenv("WORLDFORGE_ENV", "production") == "development"
        remote = os.getenv("WORLDFORGE_DATABASE_URL")
        if remote and not remote.startswith(("postgresql://", "postgres://")):
            raise ValueError("WORLDFORGE_DATABASE_URL must be a PostgreSQL URL")
        if os.getenv("WORLDFORGE_REQUIRE_POSTGRES", "0") == "1" and not remote:
            raise ValueError("This hosted shard requires a PostgreSQL database URL")
        return cls(database=remote or os.getenv("WORLDFORGE_DB", "worldforge.db"), development=dev,
                   allow_mock_locations=dev and os.getenv("WORLDFORGE_ALLOW_MOCK", "0") == "1")


CONTENT_ROOT = Path(os.getenv("WORLDFORGE_CONTENT_DIR", Path(__file__).resolve().parents[3] / "content"))
