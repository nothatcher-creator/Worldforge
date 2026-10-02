"""Run the same gameplay tests on SQLite or an isolated local PostgreSQL schema."""
import os
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
import uuid

import pytest


@pytest.fixture
def database_path():
    base = os.getenv("WORLDFORGE_TEST_POSTGRES")
    if not base:
        yield lambda path: str(path)
        return

    import psycopg
    from psycopg import sql

    parts = urlsplit(base)
    # This test fixture creates/drops its own schemas. Never target a live shard.
    if parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail("WORLDFORGE_TEST_POSTGRES must target a local integration database")
    schemas = {}
    connection = psycopg.connect(base, autocommit=True)

    def resolve(path):
        key = str(path)
        if key not in schemas:
            schema = "wfqa_" + uuid.uuid4().hex
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            schemas[key] = schema
        query = dict(parse_qsl(parts.query))
        query["options"] = "-c search_path=" + schemas[key]
        return urlunsplit(parts._replace(query=urlencode(query, quote_via=quote)))

    try:
        yield resolve
    finally:
        for schema in schemas.values():
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        connection.close()
