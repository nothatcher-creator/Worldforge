"""PostgreSQL transport for the shard's existing transactional database API."""
from contextlib import contextmanager
from urllib.parse import urlsplit

import psycopg


class Record(dict):
    """Like sqlite3.Row: named fields plus positional access for existing queries."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def record_factory(cursor):
    names = [column.name for column in cursor.description or ()]
    return lambda values: Record(zip(names, values))


def parameters(sql):
    """Translate qmark placeholders, preserving quoted SQL and literal percent signs.

    Queries are trusted repository code; player data stays in bound parameters.
    The shard uses ordinary SQL quoted strings/identifiers, never dollar quoting.
    """
    output, quote, index = [], None, 0
    while index < len(sql):
        char = sql[index]
        if quote:
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(char * 2)
                    index += 2
                    continue
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char == "?":
            output.append("%s")
            index += 1
            continue
        output.append("%%" if char == "%" else char)
        index += 1
    return "".join(output)


class PostgresConnection:
    def __init__(self, database):
        self.database = database
        self.inside_transaction = False
        self.connection = self._connect()

    def _connect(self):
        tls = {}
        if urlsplit(self.database).hostname not in ("localhost", "127.0.0.1", "::1"):
            # Use the OS roots and verify the hostname, including for Neon URLs
            # that were copied with the weaker sslmode=require default.
            tls = {"sslmode": "verify-full", "sslrootcert": "system"}
        return psycopg.connect(self.database, autocommit=True, row_factory=record_factory,
                               prepare_threshold=None, connect_timeout=10, **tls)

    def _reconnect(self):
        self.connection.close()
        self.connection = self._connect()

    def execute(self, sql, params=()):
        if self.connection.closed and not self.inside_transaction:
            self._reconnect()
        query = parameters(sql) if params else sql
        try:
            return self.connection.execute(query, params or None)
        except psycopg.OperationalError:
            # Only replay a read outside a transaction. Never repeat a write or
            # COMMIT whose result may already have reached the database server.
            if self.inside_transaction or not sql.lstrip().upper().startswith("SELECT "):
                raise
            self._reconnect()
            return self.connection.execute(query, params or None)

    @contextmanager
    def transaction(self):
        # Wake/reconnect a suspended compute before beginning any mutations.
        self.execute("SELECT 1")
        with self.connection.transaction():
            self.inside_transaction = True
            try:
                # Match SQLite BEGIN IMMEDIATE across operator and game processes.
                # It also serializes schema/content bootstrap during a redeploy.
                self.execute("SELECT pg_advisory_xact_lock(hashtext(current_schema()), 1464226627)")
                yield self
            finally:
                self.inside_transaction = False

    def close(self):
        self.connection.close()
