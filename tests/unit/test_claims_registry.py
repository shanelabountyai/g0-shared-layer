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


# -- D-23: all-numbers rule, sample sizes, same-metric contradictions ------------------------------

@pytest.mark.parametrize("claim", [
    "88% of orgs use AI in at least one function and 95% report EBIT impact",   # 95% not in the registry
    "88% of orgs use AI; 75% report any EBIT impact",                            # 39% is the figure
    "42% of companies abandoned most AI initiatives in 2025, up from 90% in 2024",  # 17% is the figure
    "Over 40% of agentic AI projects canceled; 99% of vendors are agent washing",   # phrase path, 99% unbacked
    "65% of AI projects fail for five root causes",                              # 65 is the sample, not a %
])
def test_one_unbacked_number_makes_a_multi_number_claim_unsupported(db, claim):
    r = run(db, claims=[claim]).results[0]
    assert r.status == "unsupported", (r.status, r.note)
    assert r.source is not None


def test_a_number_that_belongs_to_a_different_metric_is_a_contradiction(db):
    # 5% is in the McKinsey row, but as "under 5% of EBIT"; the EBIT-impact figure is 39%.
    r = run(db, claims=["Only 5% of companies report any EBIT impact from AI"]).results[0]
    assert r.status == "unsupported" and r.matched_on == "number"
    assert r.source.registry_id == "mckinsey-2025-adoption-ebit"
    assert "5%" in r.note and "39%" in r.note


@pytest.mark.parametrize("claim", [
    "105 orgs report EBIT impact from AI",                     # 105 countries is the sample
    "1,993 orgs use AI in at least one function",              # 1,993 respondents is the sample
    "1993% of orgs use AI in at least one function",
    "Only 1,000 companies abandoned most AI initiatives",      # ~1,000 respondents is the sample
    "AI projects fail for 65 root causes of failure for ai projects",
])
def test_sample_sizes_never_support_a_claim(db, claim):
    r = run(db, claims=[claim]).results[0]
    assert r.status == "unsupported", (r.status, r.note)


def test_registry_numbers_exclude_the_sample(db):
    rows = {r["id"]: r for r in cap._rows(db)}
    assert "1993" not in rows["mckinsey-2025-adoption-ebit"]["numbers"]
    assert "105" not in rows["mckinsey-2025-adoption-ebit"]["numbers"]
    assert "65" not in rows["rand-2024-root-causes"]["numbers"]


def test_a_correctly_cited_sample_size_does_not_block(db):
    r = run(db, claims=["McKinsey surveyed 1,993 respondents: 88% of orgs use AI in at least one function"]).results[0]
    assert r.status == "supported" and "1993 (sample)" in r.note
    r = run(db, claims=["The five root causes study covered 65 interviews."]).results[0]
    assert r.status == "supported" and r.matched_on == "phrase"


@pytest.mark.parametrize("claim,rid", [
    ("88% of orgs use AI in at least one function and only 39% report any EBIT impact", "mckinsey-2025-adoption-ebit"),
    ("42% of companies abandoned most AI initiatives in 2025, up from 17% in 2024", "sp-global-2025-abandonment"),
    ("Only 5% of companies are future-built; 60% get minimal or no material value", "bcg-2025-value-gap"),
])
def test_fully_backed_multi_number_claim_is_supported(db, claim, rid):
    r = run(db, claims=[claim]).results[0]
    assert r.status == "supported", r.note
    assert r.source.registry_id == rid


def test_claim_mixing_two_registry_rows_is_supported_when_each_number_is_backed(db):
    r = run(db, claims=["88% of orgs use AI in at least one function, yet 42% of companies abandoned most AI initiatives"]).results[0]
    assert r.status == "supported", r.note
    assert "mckinsey-2025-adoption-ebit" in r.note and "sp-global-2025-abandonment" in r.note


# -- D-24: offer / price figures are not market statistics ---------------------------------------

def test_discount_copy_is_not_blocked(db):
    r = run(db, claims=["save 15% - our people and process track"]).results[0]
    assert r.status != "unsupported" and r.status != "needs_source"
    assert "15% (offer)" in r.note


@pytest.mark.parametrize("claim", ["Get 20% off the audit this month", "The audit is $499/mo for 12 months"])
def test_offer_only_claim_is_supported_without_a_source(db, claim):
    r = run(db, claims=[claim]).results[0]
    assert r.status == "supported" and r.matched_on == "none" and r.source is None
    assert "offer" in r.note


def test_offer_sentences_are_not_extracted_from_text(db):
    out = run(db, text="Save 15% - our people and process track. Only 39% of companies report any EBIT impact from AI.")
    assert [r.claim for r in out.results] == ["Only 39% of companies report any EBIT impact from AI."]
    assert out.results[0].status == "supported"


def test_offer_figure_does_not_launder_a_wrong_stat(db):
    r = run(db, claims=["Save 15% today: 95% of orgs use AI in at least one function"]).results[0]
    assert r.status == "unsupported" and "95%" in r.note


# -- phrase boundaries ---------------------------------------------------------------------------

@pytest.mark.parametrize("claim", [
    "Our nonfuture-builtin stack is 50% faster",
    "Teams that redesign workflowsx see 3x gains",
    "Their agent washingmachine sold 40% more",
])
def test_key_phrase_must_match_on_word_boundaries(db, claim):
    r = run(db, claims=[claim]).results[0]
    assert r.matched_on != "phrase", r.note


def test_key_phrase_matches_on_boundaries_with_punctuation(db):
    r = run(db, claims=["Only 5% of companies are \"future-built\" and get AI value at scale."]).results[0]
    assert r.status == "supported" and r.matched_on == "phrase" and r.source.registry_id == "bcg-2025-value-gap"


def test_comma_grouped_count_is_not_a_year():
    assert normalized_numbers("1,993 respondents in 2025") == {"1993"}
