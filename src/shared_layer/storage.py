"""SQLite storage: one file (D-6), schema, and the seed loader (C2).

The path comes from `G0_DB_PATH`; the default is `~/.g0-shared-layer/layer.sqlite`.
`:memory:` is what the tests use. Seeding is idempotent: seed rows are
`INSERT OR REPLACE`d by their ids, so re-running the server never duplicates
them, and nothing a consumer wrote (events, run_log, health_log, evaluations)
is touched.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

def default_db_path() -> Path:
    return Path.home() / ".g0-shared-layer" / "layer.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    stat TEXT NOT NULL,
    publisher TEXT NOT NULL,
    title TEXT NOT NULL,
    sample TEXT NOT NULL,
    url TEXT NOT NULL,
    key_phrases TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS brand_policies (
    policy_version TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    text TEXT NOT NULL,
    channels TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brand_rules (
    id TEXT NOT NULL,
    policy_version TEXT NOT NULL REFERENCES brand_policies(policy_version),
    kind TEXT NOT NULL,
    pattern TEXT,
    "limit" INTEGER,
    channels TEXT NOT NULL,
    severity TEXT NOT NULL,
    fix TEXT NOT NULL,
    PRIMARY KEY (id, policy_version)
);
CREATE TABLE IF NOT EXISTS contacts (
    contact_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    title TEXT,
    company TEXT,
    do_not_contact INTEGER NOT NULL DEFAULT 0,
    consent_recorded_at TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consent (
    contact_id TEXT NOT NULL REFERENCES contacts(contact_id),
    channel TEXT NOT NULL,
    allowed INTEGER NOT NULL,
    PRIMARY KEY (contact_id, channel)
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event TEXT NOT NULL,
    fields TEXT NOT NULL,
    run_id TEXT,
    agent TEXT,
    occurred_at TEXT NOT NULL,
    stored_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_name ON events(event, occurred_at);
CREATE TABLE IF NOT EXISTS run_log (
    log_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    step TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd REAL NOT NULL,
    status TEXT NOT NULL,
    duration_ms INTEGER,
    note TEXT,
    logged_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_log_by_run ON run_log(run_id);
CREATE TABLE IF NOT EXISTS health_log (
    checked_at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rubrics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    pass_threshold REAL NOT NULL,
    criteria TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id TEXT PRIMARY KEY,
    rubric_id TEXT NOT NULL,
    judge TEXT NOT NULL,
    item TEXT NOT NULL,
    result TEXT NOT NULL,
    evaluated_at TEXT NOT NULL
);
"""

SEED_FILES = {
    "claims": "claims.json",
    "brand_policy": "brand_policy_v1.json",
    "contacts": "contacts.json",
    "rubrics": "rubrics.json",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def db_path_from_env() -> str:
    return os.environ.get("G0_DB_PATH") or str(default_db_path())


def load_seed(name: str) -> dict[str, Any]:
    """Read one seed file shipped inside the package (D-20)."""
    file = resources.files("shared_layer.seeds").joinpath(SEED_FILES[name])
    return json.loads(file.read_text(encoding="utf-8"))


class Database:
    """A thin wrapper over one sqlite3 connection. Not thread-safe by design: the
    MCP server handles one call at a time per process."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or db_path_from_env()
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(Path(self.path).expanduser()) if self.path != ":memory:" else self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.started_at = time.monotonic()

    # -- seeds ---------------------------------------------------------------

    def seed(self) -> dict[str, int]:
        """Load every seed file. Idempotent. Returns row counts after seeding."""
        with self.conn:
            self._seed_claims(load_seed("claims"))
            self._seed_brand_policy(load_seed("brand_policy"))
            self._seed_contacts(load_seed("contacts"))
            self._seed_rubrics(load_seed("rubrics"))
        return self.seed_counts()

    def _seed_claims(self, doc: dict[str, Any]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO claims (id, stat, publisher, title, sample, url, key_phrases) VALUES (?,?,?,?,?,?,?)",
            [
                (c["id"], c["stat"], c["publisher"], c["title"], c["sample"], c["url"], json.dumps(c.get("key_phrases", [])))
                for c in doc["claims"]
            ],
        )

    def _seed_brand_policy(self, doc: dict[str, Any]) -> None:
        pv = doc["policy_version"]
        self.conn.execute(
            "INSERT OR REPLACE INTO brand_policies (policy_version, source, text, channels) VALUES (?,?,?,?)",
            (pv, doc["source"], doc["text"], json.dumps(doc["channels"])),
        )
        self.conn.executemany(
            'INSERT OR REPLACE INTO brand_rules (id, policy_version, kind, pattern, "limit", channels, severity, fix) VALUES (?,?,?,?,?,?,?,?)',
            [
                (r["id"], pv, r["kind"], r.get("pattern"), r.get("limit"), json.dumps(r["channels"]), r["severity"], r["fix"])
                for r in doc["rules"]
            ],
        )

    def _seed_contacts(self, doc: dict[str, Any]) -> None:
        for c in doc["contacts"]:
            if not c["email"].lower().endswith("@example.com"):
                raise ValueError(f"contact {c['contact_id']} is not on example.com; synthetic contacts only (D-9)")
            self.conn.execute(
                "INSERT OR REPLACE INTO contacts (contact_id, email, name, title, company, do_not_contact, consent_recorded_at, source) VALUES (?,?,?,?,?,?,?,?)",
                (
                    c["contact_id"], c["email"].lower(), c["name"], c.get("title"), c.get("company"),
                    1 if c.get("do_not_contact") else 0, c["consent_recorded_at"], c["source"],
                ),
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO consent (contact_id, channel, allowed) VALUES (?,?,?)",
                [(c["contact_id"], ch, 1 if ok else 0) for ch, ok in c["consent"].items()],
            )

    def _seed_rubrics(self, doc: dict[str, Any]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO rubrics (id, title, source, pass_threshold, criteria) VALUES (?,?,?,?,?)",
            [(r["id"], r["title"], r["source"], r["pass_threshold"], json.dumps(r["criteria"])) for r in doc["rubrics"]],
        )

    def seed_counts(self) -> dict[str, int]:
        q = lambda sql: int(self.conn.execute(sql).fetchone()[0])  # noqa: E731
        return {
            "claims": q("SELECT COUNT(*) FROM claims"),
            "brand_rules": q("SELECT COUNT(*) FROM brand_rules"),
            "brand_policies": q("SELECT COUNT(*) FROM brand_policies"),
            "contacts": q("SELECT COUNT(*) FROM contacts"),
            "rubrics": q("SELECT COUNT(*) FROM rubrics"),
        }

    # -- health --------------------------------------------------------------

    def writable(self) -> bool:
        try:
            with self.conn:
                self.conn.execute("CREATE TABLE IF NOT EXISTS _probe (x INTEGER)")
                self.conn.execute("INSERT INTO _probe VALUES (1)")
                self.conn.execute("DELETE FROM _probe")
            return True
        except sqlite3.Error:
            return False

    def uptime_s(self) -> float:
        return round(time.monotonic() - self.started_at, 3)

    def close(self) -> None:
        self.conn.close()


def open_database(path: str | None = None) -> Database:
    """Open (creating if needed) and seed. What the server and the tests call."""
    db = Database(path)
    db.seed()
    return db
