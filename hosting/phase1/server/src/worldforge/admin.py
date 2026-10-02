"""Local operator provisioning; no public endpoint can assign staff roles."""
import argparse
import getpass
from pathlib import Path

from .config import Settings
from .game import Game
from .schemas import Credentials


def main():
    parser = argparse.ArgumentParser(description="World shard operator tools")
    parser.add_argument("command", choices=["create-owner", "backup"])
    parser.add_argument("--email")
    parser.add_argument("--password-file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    game = Game(Settings.from_env())
    try:
        if args.command == "backup":
            if game.db.backend != "sqlite":
                parser.error("PostgreSQL backups use pg_dump or a provider export; see docs/free-hosting.md")
            import sqlite3
            if not args.output:
                parser.error("backup requires --output")
            target = sqlite3.connect(args.output)
            with game.db.lock:
                game.db.conn.backup(target)
            target.close()
            print(f"Consistent SQLite backup saved to {args.output}")
            return
        if not args.email:
            parser.error("create-owner requires --email")
        password = args.password_file.read_text().strip() if args.password_file else getpass.getpass("New owner password (10+ characters): ")
        credentials = Credentials(email=args.email, password=password)
        game.register(credentials, role="OWNER")
        with game.db.transaction() as c:
            owner = c.execute("SELECT id FROM users WHERE email=?", (credentials.email,)).fetchone()[0]
            c.execute("INSERT INTO audit_logs(actor,action,timestamp,object_id,reason) VALUES(?,?,?,?,?)",
                      (owner, "owner.provision", __import__("time").time(), owner, "Local operator provisioning"))
        print("Owner account provisioned. Sign in from the Android client with the supplied email/password.")
    finally:
        game.db.close()


if __name__ == "__main__":
    main()
