"""C8: evaluation (D-19). No live model call anywhere in this file."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared_layer.capabilities import evaluation as cap
from shared_layer.capabilities import observability
from shared_layer.errors import Refusal

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "evaluation_fixture.json"


def run(db, with_judge=None, **kw):
    return cap.run(db, cap.Input(**kw), judge=with_judge)


# -- deterministic ---------------------------------------------------------------


def test_post_angle_passes_when_specific_and_clean(db):
    out = run(db, rubric_id="post_angle_v1", item="At 1,000 projects a year, the intake form was the bottleneck, not the people.", judge="deterministic")
    assert out.ok and out.judge == "deterministic" and out.passed and out.total == 1.0 and out.usage is None
    assert [s.criterion for s in out.scores] == ["one_sentence", "max_25_words", "no_banned_phrases", "specific", "no_hype"]


def test_post_angle_fails_on_a_required_criterion(db):
    out = run(db, rubric_id="post_angle_v1", item="Excited to share: at 1,000 projects a year the intake form was the bottleneck.", judge="deterministic")
    assert not out.passed
    bad = {s.criterion: s for s in out.scores}["no_banned_phrases"]
    assert bad.score == 0.0 and "never_use.excited_to_share" in bad.note


def test_post_angle_generality_and_hype_lower_the_total_without_failing_required(db):
    out = run(db, rubric_id="post_angle_v1", item="This will revolutionize how teams think about work.", judge="deterministic")
    scores = {s.criterion: s.score for s in out.scores}
    assert scores["specific"] == 0.0 and scores["no_hype"] == 0.0
    assert out.total == 0.6 and not out.passed  # below the 0.8 threshold


def test_claim_rule_checks_numbers_urls_and_quotes_against_context(db):
    context = 'Acme cut intake from 12 steps to 1, said the CMO: "we removed every approval". https://example.com/a'
    good = 'Acme cut intake from 12 steps to 1 ("we removed every approval"). https://example.com/a'
    out = run(db, rubric_id="claim_rule_v1", item=good, context=context, judge="deterministic")
    assert out.passed and out.total == 1.0
    bad = 'Acme cut intake from 15 steps to 1 ("we fired everyone"). https://example.com/b'
    out = run(db, rubric_id="claim_rule_v1", item=bad, context=context, judge="deterministic")
    assert not out.passed and all(s.score == 0.0 for s in out.scores)
    assert "15" in out.scores[0].note and "example.com/b" in out.scores[1].note


def test_claim_rule_without_context_cannot_pass(db):
    out = run(db, rubric_id="claim_rule_v1", item="12 steps to 1", judge="deterministic")
    assert not out.passed and "no context" in out.scores[0].note


def test_digest_item_scores_an_object(db):
    item = {"summary": "First sentence. Second sentence.", "tag": "agent-readiness", "post_angle": "One number: 12 steps to 1 beats a generality."}
    out = run(db, rubric_id="digest_item_v1", item=item, judge="deterministic")
    assert out.passed and out.total == 1.0
    item["tag"] = "spam"
    item["post_angle"] = "A game-changer for everyone."
    out = run(db, rubric_id="digest_item_v1", item=item, judge="deterministic")
    scores = {s.criterion: s.score for s in out.scores}
    assert scores["valid_tag"] == 0.0 and scores["angle_in_voice"] == 0.0 and not out.passed


def test_unknown_rubric_is_a_typed_refusal(db):
    with pytest.raises(Refusal) as e:
        run(db, rubric_id="nope", item="x", judge="deterministic")
    assert e.value.envelope.code == "UNKNOWN_RUBRIC" and e.value.envelope.next.tool == "health"


def test_evaluations_are_stored(db):
    out = run(db, rubric_id="post_angle_v1", item="Twelve steps became one.", judge="deterministic")
    row = db.conn.execute("SELECT * FROM evaluations WHERE evaluation_id = ?", (out.evaluation_id,)).fetchone()
    assert row["judge"] == "deterministic" and json.loads(row["result"])["rubric_id"] == "post_angle_v1"


# -- fixture ---------------------------------------------------------------------


def test_fixture_judge_replays_the_file(db, monkeypatch):
    monkeypatch.setenv("G0_EVAL_FIXTURE", str(FIXTURE))
    out = run(db, rubric_id="post_angle_v1", item="anything", judge="fixture")
    assert out.judge == "fixture" and out.passed and out.total == 0.9
    assert out.usage is not None and out.usage.model == "claude-sonnet-5-5"
    out = run(db, rubric_id="digest_item_v1", item={"x": 1}, judge="fixture")
    assert out.passed and out.total == 0.75  # threshold is 0.75, required criteria met


def test_fixture_is_labelled_as_hand_written():
    doc = json.loads(FIXTURE.read_text())
    assert "NOT a recorded live model response" in doc["_about"]


# -- auto selection and the Claude judge, with a fake client -------------------------


def test_auto_picks_deterministic_without_a_key(db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert run(db, rubric_id="post_angle_v1", item="Twelve steps became one.", judge="auto").judge == "deterministic"


def test_claude_judge_refuses_without_a_key(db, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(Refusal) as e:
        run(db, rubric_id="post_angle_v1", item="x", judge="claude")
    assert e.value.envelope.code == "JUDGE_UNAVAILABLE" and e.value.envelope.next.tool == "evaluation"


class FakeMessages:
    def __init__(self, reply: dict, in_tok=640, out_tok=210):
        self.reply, self.in_tok, self.out_tok, self.calls = reply, in_tok, out_tok, 0

    def create(self, **kwargs):
        self.calls += 1
        self.last = kwargs
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(self.reply))], usage=SimpleNamespace(input_tokens=self.in_tok, output_tokens=self.out_tok))


def fake_client(reply, **kw):
    return SimpleNamespace(messages=FakeMessages(reply, **kw))


def test_claude_judge_scores_logs_tokens_and_cost(db):
    reply = {"scores": [{"criterion": "one_sentence", "score": 1, "note": "ok"}, {"criterion": "max_25_words", "score": 1, "note": "ok"},
                        {"criterion": "no_banned_phrases", "score": 1, "note": "ok"}, {"criterion": "specific", "score": 0.5, "note": "half"}],
             "notes": "fine"}
    client = fake_client(reply, in_tok=1000, out_tok=200)
    judge = cap.ClaudeJudge(model="claude-sonnet-5-5", client=client)
    out = run(db, with_judge=judge, rubric_id="post_angle_v1", item="Twelve steps became one.", run_id="run-7")
    assert out.judge == "claude" and out.ok
    assert out.usage.input_tokens == 1000 and out.usage.output_tokens == 200
    assert out.usage.cost_usd == pytest.approx(1000 * 2 / 1e6 + 200 * 10 / 1e6)
    by = {s.criterion: s for s in out.scores}
    assert by["specific"].score == 0.5 and by["no_hype"].score == 0.0 and "not scored" in by["no_hype"].note
    assert out.total == 0.7 and out.passed is False  # required criteria met, but 0.7 < the 0.8 threshold
    total = observability.run_total(db, "run-7")
    assert total.calls == 1 and total.cost_usd == pytest.approx(out.usage.cost_usd)
    assert client.messages.last["model"] == "claude-sonnet-5-5"
    assert "Never invent facts" in client.messages.last["system"]


def test_claude_judge_refuses_past_the_cap_and_makes_no_call(db, monkeypatch):
    monkeypatch.setenv("G0_RUN_CAP_USD", "1.0")
    observability.run(db, observability.Input(run_id="run-8", agent="x", step="y", cost_usd=1.0))
    client = fake_client({"scores": [], "notes": ""})
    with pytest.raises(Refusal) as e:
        run(db, with_judge=cap.ClaudeJudge(model="claude-sonnet-5-5", client=client), rubric_id="post_angle_v1", item="x", run_id="run-8")
    assert e.value.envelope.code == "OVER_CAP" and client.messages.calls == 0


def test_claude_judge_refuses_a_model_without_a_price(db):
    client = fake_client({"scores": [], "notes": ""})
    with pytest.raises(Refusal) as e:
        run(db, with_judge=cap.ClaudeJudge(model="claude-mystery-9", client=client), rubric_id="post_angle_v1", item="x")
    assert e.value.envelope.code == "JUDGE_UNAVAILABLE" and client.messages.calls == 0
