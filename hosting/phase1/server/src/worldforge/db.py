from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading

import psycopg

from .postgres import PostgresConnection


INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)


# Schema migrations are numbered, additive, and applied atomically at startup.
SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS users(
 id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'PLAYER', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS characters(
 id TEXT PRIMARY KEY, user_id TEXT UNIQUE NOT NULL REFERENCES users(id), name TEXT NOT NULL,
 level INTEGER NOT NULL DEFAULT 1 CHECK(level BETWEEN 1 AND 120), xp INTEGER NOT NULL DEFAULT 0,
 gold INTEGER NOT NULL DEFAULT 0 CHECK(gold>=0), xp_locked INTEGER NOT NULL DEFAULT 0,
 visible INTEGER NOT NULL DEFAULT 1, passenger INTEGER NOT NULL DEFAULT 0,
 origin_region TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS player_locations(
 character_id TEXT PRIMARY KEY REFERENCES characters(id), lat REAL NOT NULL, lon REAL NOT NULL,
 accuracy REAL NOT NULL, speed REAL NOT NULL DEFAULT 0, cell_lat INTEGER NOT NULL, cell_lon INTEGER NOT NULL,
 received_at REAL NOT NULL, restricted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS location_cells ON player_locations(cell_lat,cell_lon);
CREATE TABLE IF NOT EXISTS location_flags(
 character_id TEXT PRIMARY KEY REFERENCES characters(id), reason TEXT NOT NULL, count INTEGER NOT NULL,
 updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS loadout(
 character_id TEXT NOT NULL REFERENCES characters(id), slot INTEGER NOT NULL CHECK(slot BETWEEN 0 AND 3),
 ability_id TEXT NOT NULL, PRIMARY KEY(character_id,slot));
CREATE TABLE IF NOT EXISTS item_instances(
 id TEXT PRIMARY KEY, character_id TEXT NOT NULL REFERENCES characters(id), definition_id TEXT NOT NULL,
 definition_version INTEGER NOT NULL, name TEXT NOT NULL, slot TEXT NOT NULL, rarity TEXT NOT NULL,
 item_level INTEGER NOT NULL, required_level INTEGER NOT NULL, icon_id TEXT NOT NULL,
 legendary_effect TEXT, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS inventory_owner ON item_instances(character_id);
CREATE TABLE IF NOT EXISTS item_stats(
 item_id TEXT NOT NULL REFERENCES item_instances(id), stat TEXT NOT NULL, value REAL NOT NULL,
 PRIMARY KEY(item_id,stat));
CREATE TABLE IF NOT EXISTS item_affixes(
 item_id TEXT NOT NULL REFERENCES item_instances(id), affix_id TEXT NOT NULL, name TEXT NOT NULL,
 stat TEXT NOT NULL, value REAL NOT NULL, PRIMARY KEY(item_id,affix_id));
CREATE TABLE IF NOT EXISTS equipment(
 character_id TEXT NOT NULL REFERENCES characters(id), slot TEXT NOT NULL,
 item_id TEXT UNIQUE NOT NULL REFERENCES item_instances(id), PRIMARY KEY(character_id,slot));
CREATE TABLE IF NOT EXISTS quest_progress(
 character_id TEXT NOT NULL REFERENCES characters(id), quest_id TEXT NOT NULL,
 progress INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
 PRIMARY KEY(character_id,quest_id));
CREATE TABLE IF NOT EXISTS skills(
 character_id TEXT NOT NULL REFERENCES characters(id), skill_id TEXT NOT NULL,
 xp INTEGER NOT NULL DEFAULT 0, next_action_at REAL NOT NULL DEFAULT 0,
 PRIMARY KEY(character_id,skill_id));
CREATE TABLE IF NOT EXISTS resources(
 character_id TEXT NOT NULL REFERENCES characters(id), resource_id TEXT NOT NULL,
 quantity INTEGER NOT NULL CHECK(quantity>=0), PRIMARY KEY(character_id,resource_id));
CREATE TABLE IF NOT EXISTS settlements(
 id TEXT PRIMARY KEY, owner_id TEXT UNIQUE NOT NULL REFERENCES characters(id), name TEXT NOT NULL,
 lat REAL NOT NULL, lon REAL NOT NULL, level INTEGER NOT NULL DEFAULT 1,
 capital INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS parties(id TEXT PRIMARY KEY, leader_id TEXT NOT NULL REFERENCES characters(id));
CREATE TABLE IF NOT EXISTS party_members(
 party_id TEXT NOT NULL REFERENCES parties(id), character_id TEXT UNIQUE NOT NULL REFERENCES characters(id),
 PRIMARY KEY(party_id,character_id));
CREATE TABLE IF NOT EXISTS party_invites(
 id TEXT PRIMARY KEY, sender_id TEXT NOT NULL REFERENCES characters(id),
 target_id TEXT NOT NULL REFERENCES characters(id), expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS blocks(
 blocker_id TEXT NOT NULL REFERENCES characters(id), blocked_id TEXT NOT NULL REFERENCES characters(id),
 PRIMARY KEY(blocker_id,blocked_id));
CREATE TABLE IF NOT EXISTS reports(
 id TEXT PRIMARY KEY, reporter_id TEXT NOT NULL REFERENCES characters(id), target_id TEXT NOT NULL,
 reason TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS monsters(
 id TEXT PRIMARY KEY, definition_id TEXT NOT NULL, cell_lat INTEGER NOT NULL, cell_lon INTEGER NOT NULL,
 lat REAL NOT NULL, lon REAL NOT NULL, respawn_at REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS monster_cells ON monsters(cell_lat,cell_lon);
CREATE TABLE IF NOT EXISTS combat_rewards(
 battle_id TEXT NOT NULL, character_id TEXT NOT NULL REFERENCES characters(id),
 xp INTEGER NOT NULL, gold INTEGER NOT NULL, item_id TEXT NOT NULL,
 PRIMARY KEY(battle_id,character_id));
CREATE TABLE IF NOT EXISTS content_definitions(
 kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, definition TEXT NOT NULL,
 PRIMARY KEY(kind,id));
CREATE TABLE IF NOT EXISTS content_versions(
 kind TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL, definition TEXT NOT NULL,
 actor TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(kind,id,version));
CREATE TABLE IF NOT EXISTS content_meta(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS audit_logs(
 id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL, action TEXT NOT NULL, timestamp REAL NOT NULL,
 object_id TEXT NOT NULL, old_value TEXT, new_value TEXT, reason TEXT NOT NULL);
INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT(version) DO NOTHING;
"""


class Database:
    def __init__(self, path: str | Path):
        self.lock = threading.RLock()
        self.backend = "postgresql" if str(path).startswith(("postgresql://", "postgres://")) else "sqlite"
        if self.backend == "postgresql":
            self.conn = PostgresConnection(str(path))
            # PostgreSQL REAL has only 32-bit precision, which is insufficient
            # for GPS positions and Unix timestamps. SQLite REAL is 64-bit.
            schema = SCHEMA.replace(" REAL ", " DOUBLE PRECISION ").replace(
                "id INTEGER PRIMARY KEY AUTOINCREMENT", "id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
            with self.conn.transaction() as connection:
                for statement in schema.split(";"):
                    if statement.strip():
                        connection.execute(statement)
            return
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.backend == "postgresql":
                with self.conn.transaction() as connection:
                    yield connection
                return
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def all(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def close(self):
        self.conn.close()
