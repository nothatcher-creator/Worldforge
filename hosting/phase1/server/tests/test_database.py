from worldforge.config import Settings
from worldforge.db import Database
import os

import pytest


def test_hosted_database_url_takes_priority_over_local_sqlite_path(monkeypatch):
    monkeypatch.setenv("WORLDFORGE_DB", "/app/data/world.db")
    monkeypatch.setenv("WORLDFORGE_DATABASE_URL", "postgresql://localhost/worldforge")
    assert Settings.from_env().database == "postgresql://localhost/worldforge"


def test_free_host_never_falls_back_to_an_ephemeral_database(monkeypatch):
    monkeypatch.setenv("WORLDFORGE_REQUIRE_POSTGRES", "1")
    monkeypatch.delenv("WORLDFORGE_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings.from_env()


def test_invalid_hosted_database_scheme_is_rejected(monkeypatch):
    monkeypatch.setenv("WORLDFORGE_DATABASE_URL", "https://localhost/database")
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings.from_env()


postgres = pytest.mark.skipif(not os.getenv("WORLDFORGE_TEST_POSTGRES"), reason="Local PostgreSQL not configured")


@postgres
def test_postgres_connection_and_transaction_rollback(database_path, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = Database(database_path(tmp_path / "postgres.db"))
    try:
        assert db.one("SELECT pg_backend_pid() AS pid")["pid"] > 0
        with pytest.raises(ValueError, match="abort"):
            with db.transaction() as c:
                c.execute("INSERT INTO users VALUES(?,?,?,?,?)", ("u", "u@test.example", "hash", "PLAYER", 0))
                raise ValueError("abort")
        assert db.one("SELECT id FROM users WHERE id=?", ("u",)) is None
    finally:
        db.close()


@postgres
def test_postgres_preserves_coordinates_and_subsecond_timestamps(database_path, tmp_path):
    path = database_path(tmp_path / "precision.db")
    db = Database(path)
    timestamp, lat, lon = 1700000000.123456, 45.95322219, -66.64722092
    with db.transaction() as c:
        c.execute("INSERT INTO users VALUES(?,?,?,?,?)", ("u", "u@test.example", "hash", "PLAYER", timestamp))
        c.execute("INSERT INTO characters(id,user_id,name,origin_region,created_at) VALUES(?,?,?,?,?)",
                  ("c", "u", "Aster", "fallback", timestamp))
        c.execute("INSERT INTO player_locations VALUES(?,?,?,?,?,?,?,?,0)",
                  ("c", lat, lon, 4.5, 0, 0, 0, timestamp))
    db.close()
    reopened = Database(path)
    try:
        row = reopened.one("SELECT * FROM player_locations WHERE character_id=?", ("c",))
        assert (row["lat"], row["lon"], row["received_at"]) == (lat, lon, timestamp)
    finally:
        reopened.close()


@postgres
def test_postgres_recovers_a_session_killed_while_idle(database_path, tmp_path):
    import psycopg
    path = database_path(tmp_path / "reconnect.db")
    db = Database(path)
    try:
        pid = db.one("SELECT pg_backend_pid() AS pid")["pid"]
        with psycopg.connect(os.environ["WORLDFORGE_TEST_POSTGRES"], autocommit=True) as operator:
            operator.execute("SELECT pg_terminate_backend(%s)", (pid,))
        assert db.one("SELECT count(*) AS count FROM users")["count"] == 0
        with db.transaction() as c:
            c.execute("INSERT INTO users VALUES(?,?,?,?,?)", ("u", "u@test.example", "hash", "PLAYER", 0))
        assert db.one("SELECT id FROM users")["id"] == "u"
    finally:
        db.close()


@postgres
def test_postgres_does_not_replay_an_interrupted_write_transaction(database_path, tmp_path):
    import psycopg
    db = Database(database_path(tmp_path / "interrupted.db"))
    try:
        pid = db.one("SELECT pg_backend_pid() AS pid")["pid"]
        with pytest.raises(psycopg.OperationalError):
            with db.transaction() as c:
                c.execute("INSERT INTO users VALUES(?,?,?,?,?)", ("u", "u@test.example", "hash", "PLAYER", 0))
                with psycopg.connect(os.environ["WORLDFORGE_TEST_POSTGRES"], autocommit=True) as operator:
                    operator.execute("SELECT pg_terminate_backend(%s)", (pid,))
                c.execute("SELECT 1")
        assert db.one("SELECT id FROM users WHERE id=?", ("u",)) is None
    finally:
        db.close()


@postgres
def test_postgres_binds_player_text_without_changing_literal_sql(database_path, tmp_path):
    db = Database(database_path(tmp_path / "parameters.db"))
    try:
        text = "'); DROP TABLE users; -- 100%?"
        row = db.one('SELECT \'50%?\' AS "literal?", ? AS bound', (text,))
        assert row == {"literal?": "50%?", "bound": text}
        assert db.one("SELECT count(*) AS count FROM users")["count"] == 0
    finally:
        db.close()


@postgres
def test_remote_postgres_cannot_downgrade_tls(database_path, tmp_path):
    from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
    import psycopg
    parts = urlsplit(database_path(tmp_path / "tls.db"))
    query = dict(parse_qsl(parts.query))
    query.update(hostaddr="127.0.0.1", sslmode="disable")
    authority = parts.netloc.replace("127.0.0.1", "wfqa-untrusted.invalid")
    remote = urlunsplit(parts._replace(netloc=authority, query=urlencode(query, quote_via=quote)))
    # The local integration database has no TLS. A remote hostname must require
    # verified TLS despite a caller asking to disable it; no DNS/network escape.
    with pytest.raises(psycopg.OperationalError, match="SSL|ssl|TLS"):
        Database(remote)
