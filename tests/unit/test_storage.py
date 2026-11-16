"""C2: schema, seed loader, fixtures (D-6, D-8, D-9)."""

from __future__ import annotations

import json
import re

from shared_layer.storage import Database, load_seed, open_database

EXPECTED = {"claims": 9, "brand_rules": 12, "brand_policies": 1, "contacts": 20, "rubrics": 3}


def test_fresh_db_seeds_to_expected_counts(db):
    assert db.seed_counts() == EXPECTED


def test_seeding_is_idempotent(db):
    db.seed()
    db.seed()
    assert db.seed_counts() == EXPECTED


def test_seeding_leaves_consumer_rows_alone(db):
    with db.conn:
        db.conn.execute("INSERT INTO events (event_id, event, fields, occurred_at, stored_at) VALUES ('e1','x.y','{}','t','t')")
    db.seed()
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


def test_every_contact_is_synthetic(db):
    rows = db.conn.execute("SELECT email, source FROM contacts").fetchall()
    assert rows
    for r in rows:
        assert r["email"].endswith("@example.com")
        assert "synthetic" in r["source"]


def test_seed_loader_refuses_a_non_example_contact(tmp_path, monkeypatch):
    doc = load_seed("contacts")
    doc["contacts"][0]["email"] = "someone@realcompany.com"
    db = Database(":memory:")
    import pytest

    with pytest.raises(ValueError, match="synthetic contacts only"):
        db._seed_contacts(doc)


def test_claims_seed_is_only_the_safe_rows():
    doc = load_seed("claims")
    text = json.dumps(doc).lower()
    # the brief's "use with caution" and "do not use" figures must not be here
    for banned in ("95% of genai pilots", "80.3%", "77% of ai failures", "8% of laggard", "2,400"):
        assert banned not in text
    for c in doc["claims"]:
        assert c["url"].startswith("https://")
        assert c["publisher"] and c["sample"]


def test_brand_policy_seed_carries_the_verbatim_rule_and_all_never_use_phrases():
    doc = load_seed("brand_policy")
    assert doc["policy_version"] == "1"
    assert doc["text"].startswith("BRAND VOICE (for post angles).")
    phrases = [r["pattern"] for r in doc["rules"] if r["kind"] == "phrase"]
    for p in ("excited to share", "humbled", "game-changer", "hope this finds you well", "pick your brain", "synergy", "circle back"):
        assert p in phrases


def test_db_path_default_is_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("G0_DB_PATH", raising=False)
    db = open_database()
    assert str(tmp_path) in db.path
    assert db.writable()
    db.close()


def test_db_path_from_env(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "layer.sqlite"
    monkeypatch.setenv("G0_DB_PATH", str(target))
    db = open_database()
    assert target.exists()
    db.close()


def test_rubric_checks_are_known_kinds():
    known = re.compile(r"^(max_sentences|max_words|brand_policy|has_number_or_proper_noun|no_hype_words|numbers_subset_of_context|urls_subset_of_context|quotes_subset_of_context|field_sentences|field_in|field_nonempty|field_brand_policy)(:.*)?$")
    for r in load_seed("rubrics")["rubrics"]:
        for c in r["criteria"]:
            assert known.match(c["check"]), c["check"]
