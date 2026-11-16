"""C6: measurement (D-22)."""

from __future__ import annotations

import json

import pytest

from shared_layer.capabilities import measurement as cap


def run(db, **kw):
    return cap.run(db, cap.Input(**kw))


def test_event_round_trips(db):
    out = run(db, event="digest.published", fields={"items": 7, "week": "2026-11-09"}, run_id="r1", agent="Editor")
    assert out.ok and out.event_id.startswith("evt_") and out.event == "digest.published"
    row = db.conn.execute("SELECT * FROM events WHERE event_id = ?", (out.event_id,)).fetchone()
    assert json.loads(row["fields"]) == {"items": 7, "week": "2026-11-09"}
    assert row["run_id"] == "r1" and row["agent"] == "Editor"
    assert row["occurred_at"] == row["stored_at"] == out.stored_at


def test_occurred_at_is_kept_when_given(db):
    out = run(db, event="feed.fetched", occurred_at="2026-11-02T06:00:00Z")
    row = db.conn.execute("SELECT occurred_at FROM events WHERE event_id = ?", (out.event_id,)).fetchone()
    assert row["occurred_at"] == "2026-11-02T06:00:00Z"


def test_ids_are_unique_and_nothing_is_overwritten(db):
    ids = {run(db, event="a.b").event_id for _ in range(50)}
    assert len(ids) == 50
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 50


@pytest.mark.parametrize("bad", ["", "Digest.Published", "has space", "a..b", "a-b"])
def test_event_name_is_dotted_lower_case(bad):
    with pytest.raises(ValueError):
        cap.Input(event=bad)


def test_fields_default_to_empty_object(db):
    out = run(db, event="ping")
    row = db.conn.execute("SELECT fields FROM events WHERE event_id = ?", (out.event_id,)).fetchone()
    assert json.loads(row["fields"]) == {}
