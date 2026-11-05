"""C4: brand.policy (D-7, D-16)."""

from __future__ import annotations

import pytest

from shared_layer.capabilities import brand_policy as cap
from shared_layer.errors import Refusal
from shared_layer.storage import load_seed

NEVER_USE = ["excited to share", "humbled", "game-changer", "hope this finds you well", "pick your brain", "synergy", "circle back"]


def run(db, **kw):
    return cap.run(db, cap.Input(**kw))


@pytest.mark.parametrize("phrase", NEVER_USE)
def test_every_never_use_phrase_is_caught_case_insensitively(db, phrase):
    out = run(db, text=f"Well, {phrase.upper()} is what they said.", channel="linkedin")
    assert out.passed is False
    assert any(v.rule_id.startswith("never_use.") and phrase.upper() in v.excerpt for v in out.violations)
    assert all(v.fix for v in out.violations)


def test_emoji_is_caught(db):
    out = run(db, text="Shipped the intake rebuild 🚀", channel="email")
    assert not out.passed and out.violations[0].rule_id == "never_use.emoji"


def test_beginner_voice_is_caught(db):
    out = run(db, text="I'm learning AI and here's what I found.", channel="linkedin")
    assert not out.passed and out.violations[0].rule_id == "beginner_voice.im_learning_ai"


def test_clean_text_passes(db):
    out = run(db, text="At 1,000 projects a year the intake form, not the people, was the bottleneck.", channel="linkedin")
    assert out.passed and out.violations == [] and out.rules_checked == 12 and out.policy_version == "1"


def test_post_angle_limits_apply_only_on_that_channel(db):
    long = " ".join(["word"] * 26) + "."
    assert run(db, text=long, channel="linkedin").passed
    out = run(db, text=long, channel="post_angle")
    assert not out.passed and [v.rule_id for v in out.violations] == ["post_angle.max_25_words"]
    two = "First sentence here. Second sentence here."
    out = run(db, text=two, channel="post_angle")
    assert [v.rule_id for v in out.violations] == ["post_angle.one_sentence"]


def test_unknown_policy_version_is_a_typed_refusal(db):
    with pytest.raises(Refusal) as e:
        run(db, text="x", channel="other", policy_version="9")
    assert e.value.envelope.code == "UNKNOWN_POLICY" and e.value.envelope.field == "policy_version"
    assert e.value.envelope.next.tool == "health"


def test_seeded_policy_text_is_the_g1_rule_verbatim(db):
    row = db.conn.execute("SELECT text FROM brand_policies WHERE policy_version='1'").fetchone()
    assert row["text"] == load_seed("brand_policy")["text"]
    assert "Never use: 'excited to share'" in row["text"]


def test_excerpt_shows_context_around_the_hit(db):
    out = run(db, text="Let us circle back on the Workfront rollout next quarter.", channel="email")
    assert "circle back" in out.violations[0].excerpt and "Workfront" in out.violations[0].excerpt
