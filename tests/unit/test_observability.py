"""C7: observability (D-18)."""

from __future__ import annotations

import pytest

from shared_layer.capabilities import observability as cap


def run(db, **kw):
    return cap.run(db, cap.Input(**kw))


def test_total_accumulates_per_run(db):
    a = run(db, run_id="r1", agent="Researcher", step="screen", model="claude-haiku-5-5", input_tokens=1000, output_tokens=100, cost_usd=0.00015)
    b = run(db, run_id="r1", agent="Editor", step="pick", model="claude-sonnet-5-5", input_tokens=2000, output_tokens=300, cost_usd=0.007)
    other = run(db, run_id="r2", agent="Editor", step="pick", input_tokens=5, output_tokens=5, cost_usd=1.0)
    assert a.run_total.calls == 1 and b.run_total.calls == 2
    assert b.run_total.input_tokens == 3000 and b.run_total.output_tokens == 400
    assert b.run_total.cost_usd == pytest.approx(0.00715)
    assert other.run_total.calls == 1 and other.run_total.cost_usd == 1.0
    assert not b.over_cap and b.cap_usd == 10.0


def test_over_cap_flips_past_the_cap_but_logging_is_never_refused(db):
    run(db, run_id="r1", agent="a", step="s", cost_usd=9.99)
    assert not run(db, run_id="r1", agent="a", step="s", cost_usd=0.005).over_cap  # 9.995
    out = run(db, run_id="r1", agent="a", step="s", cost_usd=0.01)  # 10.005
    assert out.ok and out.over_cap and out.log_id.startswith("log_")
    assert db.conn.execute("SELECT COUNT(*) FROM run_log WHERE run_id='r1'").fetchone()[0] == 3


def test_cap_comes_from_env(db, monkeypatch):
    monkeypatch.setenv("G0_RUN_CAP_USD", "0.5")
    out = run(db, run_id="r9", agent="a", step="s", cost_usd=0.6)
    assert out.cap_usd == 0.5 and out.over_cap
    monkeypatch.setenv("G0_RUN_CAP_USD", "not-a-number")
    assert run(db, run_id="r9", agent="a", step="s").cap_usd == 10.0


def test_status_and_note_are_stored(db):
    out = run(db, run_id="r1", agent="Writer", step="draft", status="error", duration_ms=1234, note="max_tokens hit")
    row = db.conn.execute("SELECT * FROM run_log WHERE log_id = ?", (out.log_id,)).fetchone()
    assert row["status"] == "error" and row["duration_ms"] == 1234 and row["note"] == "max_tokens hit"


@pytest.mark.parametrize("kw", [{"input_tokens": -1}, {"cost_usd": -0.1}, {"status": "meh"}, {"run_id": ""}])
def test_bad_values_are_refused(kw):
    base = {"run_id": "r", "agent": "a", "step": "s"}
    with pytest.raises(ValueError):
        cap.Input(**{**base, **kw})
