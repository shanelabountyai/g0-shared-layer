"""C3: claims.registry (D-15)."""

from __future__ import annotations

import pytest

from shared_layer.capabilities import claims_registry as cap
from shared_layer.text import normalized_numbers


def run(db, **kw):
    return cap.run(db, cap.Input(**kw))


def test_known_stat_is_supported_with_its_source(db):
    out = run(db, claims=["88% of orgs use AI in at least one function"])
    r = out.results[0]
    assert out.ok and r.status == "supported" and r.matched_on == "number"
    assert r.source is not None and r.source.publisher == "McKinsey"
    assert r.source.url.startswith("https://www.mckinsey.com/")
    assert out.registry_size == 9


def test_wrong_number_on_a_known_topic_is_unsupported(db):
    r = run(db, claims=["95% of orgs use AI in at least one function"]).results[0]
    assert r.status == "unsupported"
    assert r.source is not None and r.source.registry_id == "mckinsey-2025-adoption-ebit"
    assert "95%" in r.note


def test_unknown_topic_needs_a_source(db):
    r = run(db, claims=["The sky is 42% blue"]).results[0]
    assert r.status == "needs_source" and r.source is None


def test_key_phrase_without_a_number_is_supported(db):
    r = run(db, claims=["BCG's 10-20-70 rule puts most of the value in people and process."]).results[0]
    assert r.status == "supported" and r.matched_on == "phrase"
    assert r.source.registry_id == "bcg-10-20-70"


def test_key_phrase_with_a_contradicting_number_is_unsupported(db):
    r = run(db, claims=["The five root causes study covered 650 interviews."]).results[0]
    assert r.status == "unsupported" and r.matched_on == "phrase"
    assert r.source.registry_id == "rand-2024-root-causes"


def test_percent_word_and_tilde_normalize(db):
    assert normalized_numbers("about 42 percent of companies") == {"42%"}
    assert normalized_numbers("~6% are high performers") == {"6%"}
    assert normalized_numbers("nearly 3x as likely in 2025") == {"3x"}
    r = run(db, claims=["42 percent of companies abandoned most AI initiatives in 2025"]).results[0]
    assert r.status == "supported" and r.source.registry_id == "sp-global-2025-abandonment"


def test_free_text_extracts_only_quantitative_sentences(db):
    text = ("Pilots stall on ownership, not models. Only 39% of companies report any EBIT impact from AI. "
            "That is the thesis. S&P says 42% abandoned most AI initiatives in 2025.")
    out = run(db, text=text)
    assert [r.claim[:12] for r in out.results] == ["Only 39% of ", "S&P says 42%"]
    assert [r.status for r in out.results] == ["supported", "supported"]


def test_input_requires_text_or_claims():
    with pytest.raises(ValueError):
        cap.Input()
    with pytest.raises(ValueError):
        cap.Input(text="   ")


def test_every_seeded_stat_supports_itself(db):
    rows = db.conn.execute("SELECT stat FROM claims").fetchall()
    out = run(db, claims=[r["stat"] for r in rows])
    assert all(r.status == "supported" for r in out.results), [(r.claim, r.status) for r in out.results if r.status != "supported"]
