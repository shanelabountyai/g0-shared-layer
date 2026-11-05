"""evaluation v1 — score an item against a rubric (D-19).

Pluggable judge:
- `DeterministicJudge` runs one check per criterion. No model call. The fallback.
- `FixtureJudge` replays a stored result file (tests, demos without a key).
- `ClaudeJudge` asks a Claude model to score the rubric as JSON, logs tokens
  and cost per call to `run_log` through observability, and refuses past the cap.

`judge: "auto"` uses Claude when `ANTHROPIC_API_KEY` is set, else deterministic.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from shared_layer.capabilities import brand_policy, observability
from shared_layer.errors import NextStep, Refusal, ToolError
from shared_layer.storage import Database, new_id, now_iso
from shared_layer.text import has_number_or_proper_noun, hype_hits, normalized_numbers, quotes, sentences, urls, word_count

CAPABILITY = "evaluation"
TOOL = "evaluation"
VERSION = "1"
DESCRIPTION = (
    "Score an item against a seeded rubric (`post_angle_v1`, `claim_rule_v1`, `digest_item_v1`). `item` is a "
    "string or an object; `context` is the source material the item must be faithful to (needed for "
    "`claim_rule_v1`). `judge`: `auto` (Claude when a key is present, else deterministic), `deterministic`, "
    "`claude`, `fixture`. Returns a score per criterion, pass/fail and notes, plus tokens and cost when a "
    "model was used. A model judge is capped by the run's cost cap."
)

# Prices per MTok carried from G1 D-8 (claude-api skill cache dated 2026-10-06).
# The owner confirms model id and prices against Anthropic's pricing page before
# the first live call (NEXT.md). Re-check is cheap; a wrong price is a silent cap breach.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
DEFAULT_JUDGE_MODEL = "claude-sonnet-5-5"
JudgeName = Literal["auto", "deterministic", "claude", "fixture"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    rubric_id: str = Field(min_length=1)
    item: str | dict[str, Any] = Field(description="The thing to score: text, or an object with named fields.")
    context: str | None = Field(default=None, description="Source material the item must stay faithful to.")
    judge: JudgeName = "auto"
    run_id: str | None = Field(default=None, description="Run to log any model call under (observability).")


class CriterionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    score: float = Field(ge=0, le=1)
    weight: float
    required: bool
    note: str


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    capability: Literal["evaluation"] = "evaluation"
    ok: bool = True
    error: ToolError | None = None
    evaluation_id: str = ""
    rubric_id: str = ""
    judge: Literal["deterministic", "claude", "fixture"] | None = None
    scores: list[CriterionScore] = Field(default_factory=list)
    total: float = Field(default=0.0, description="Weighted score, 0–1.")
    passed: bool = False
    notes: str = ""
    usage: Usage | None = Field(default=None, description="Tokens and cost when a model judged; null otherwise.")


# -- rubric ------------------------------------------------------------------


class Rubric(BaseModel):
    id: str
    title: str
    source: str
    pass_threshold: float
    criteria: list[dict[str, Any]]


def load_rubric(db: Database, rubric_id: str) -> Rubric:
    row = db.conn.execute("SELECT * FROM rubrics WHERE id = ?", (rubric_id,)).fetchone()
    if row is None:
        known = [r[0] for r in db.conn.execute("SELECT id FROM rubrics ORDER BY id")]
        raise Refusal(ToolError(code="UNKNOWN_RUBRIC", message=f"No rubric '{rubric_id}'. Known: {known}.", field="rubric_id",
                                next=NextStep(tool="health", why="lists the seeded rubrics")))
    return Rubric(id=row["id"], title=row["title"], source=row["source"], pass_threshold=row["pass_threshold"], criteria=json.loads(row["criteria"]))


def decide(rubric: Rubric, scores: list[CriterionScore]) -> tuple[float, bool]:
    weight = sum(s.weight for s in scores) or 1.0
    total = round(sum(s.score * s.weight for s in scores) / weight, 4)
    required_ok = all(s.score >= 1.0 for s in scores if s.required)
    return total, bool(required_ok and total >= rubric.pass_threshold)


# -- judges ------------------------------------------------------------------


class JudgeResult(BaseModel):
    scores: list[CriterionScore]
    notes: str
    usage: Usage | None = None


class Judge(Protocol):
    name: Literal["deterministic", "claude", "fixture"]

    def judge(self, db: Database, rubric: Rubric, item: str | dict[str, Any], context: str | None, run_id: str | None) -> JudgeResult: ...


def _item_text(item: str | dict[str, Any]) -> str:
    return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


def _field(item: str | dict[str, Any], name: str) -> str | None:
    if isinstance(item, dict) and name in item and item[name] is not None:
        return str(item[name])
    return None


class DeterministicJudge:
    name: Literal["deterministic", "claude", "fixture"] = "deterministic"

    def judge(self, db: Database, rubric: Rubric, item: str | dict[str, Any], context: str | None, run_id: str | None) -> JudgeResult:
        scores = [self._score(db, c, item, context) for c in rubric.criteria]
        failed = [s.criterion for s in scores if s.score < 1.0]
        notes = "Deterministic checks; no model call. " + (f"Below 1.0: {', '.join(failed)}." if failed else "All criteria met.")
        return JudgeResult(scores=scores, notes=notes)

    def _score(self, db: Database, c: dict[str, Any], item: str | dict[str, Any], context: str | None) -> CriterionScore:
        check: str = c["check"]
        kind, _, arg = check.partition(":")
        text = _item_text(item)
        score, note = 1.0, "ok"
        if kind == "max_sentences":
            n = len(sentences(text))
            score, note = (1.0, f"{n} sentence(s)") if n <= int(arg) else (0.0, f"{n} sentences, limit {arg}")
        elif kind == "max_words":
            n = word_count(text)
            score, note = (1.0, f"{n} words") if n <= int(arg) else (0.0, f"{n} words, limit {arg}")
        elif kind == "brand_policy":
            out = brand_policy.run(db, brand_policy.Input(text=text, channel=arg))  # type: ignore[arg-type]
            score, note = (1.0, "no brand-policy violation") if out.passed else (0.0, "; ".join(f"{v.rule_id}: {v.excerpt}" for v in out.violations))
        elif kind == "has_number_or_proper_noun":
            ok = has_number_or_proper_noun(text)
            score, note = (1.0, "names a number or a proper noun") if ok else (0.0, "no number or named thing; heuristic for 'specific over general'")
        elif kind == "no_hype_words":
            hits = hype_hits(text)
            score, note = (1.0, "no hype words") if not hits else (0.0, f"hype words: {', '.join(hits)}")
        elif kind in ("numbers_subset_of_context", "urls_subset_of_context", "quotes_subset_of_context"):
            if context is None:
                score, note = 0.0, "no context given; the claim rule cannot be checked without the source item"
            elif kind == "numbers_subset_of_context":
                missing = normalized_numbers(text) - normalized_numbers(context)
                score, note = (1.0, "every number is in the source") if not missing else (0.0, f"numbers not in source: {sorted(missing)}")
            elif kind == "urls_subset_of_context":
                missing = urls(text) - urls(context)
                score, note = (1.0, "every URL is in the source") if not missing else (0.0, f"URLs not in source: {sorted(missing)}")
            else:
                missing = [q for q in quotes(text) if q not in context]
                score, note = (1.0, "every quote is in the source") if not missing else (0.0, f"quotes not in source: {missing}")
        elif kind == "field_sentences":
            fname, _, n_str = arg.partition(":")
            val = _field(item, fname)
            if val is None:
                score, note = 0.0, f"item has no field '{fname}'"
            else:
                n = len(sentences(val))
                score, note = (1.0, f"{fname}: {n} sentences") if n == int(n_str) else (0.0, f"{fname}: {n} sentences, want {n_str}")
        elif kind == "field_in":
            fname, _, allowed = arg.partition(":")
            val = _field(item, fname)
            ok = val is not None and val in allowed.split(",")
            score, note = (1.0, f"{fname}={val}") if ok else (0.0, f"{fname}={val!r} not in {allowed.split(',')}")
        elif kind == "field_nonempty":
            val = _field(item, arg)
            score, note = (1.0, f"{arg} present") if val and val.strip() else (0.0, f"{arg} missing or empty")
        elif kind == "field_brand_policy":
            fname, _, channel = arg.partition(":")
            val = _field(item, fname)
            if val is None:
                score, note = 0.0, f"item has no field '{fname}'"
            else:
                out = brand_policy.run(db, brand_policy.Input(text=val, channel=channel))  # type: ignore[arg-type]
                score, note = (1.0, f"{fname} passes brand policy") if out.passed else (0.0, "; ".join(f"{v.rule_id}: {v.excerpt}" for v in out.violations))
        else:
            score, note = 0.0, f"unknown check '{check}'"
        return CriterionScore(criterion=c["id"], score=score, weight=float(c.get("weight", 1)), required=bool(c.get("required", False)), note=note)


class FixtureJudge:
    """Replays a stored JudgeResult per rubric id from a JSON file
    (`G0_EVAL_FIXTURE`, default tests/fixtures/evaluation_fixture.json). The
    shipped file is a hand-written sample in the Claude judge's output shape, not
    a recorded live response (D-19)."""

    name: Literal["deterministic", "claude", "fixture"] = "fixture"

    def __init__(self, path: str | None = None) -> None:
        self.path = path or os.environ.get("G0_EVAL_FIXTURE") or os.path.join(os.getcwd(), "tests", "fixtures", "evaluation_fixture.json")

    def judge(self, db: Database, rubric: Rubric, item: str | dict[str, Any], context: str | None, run_id: str | None) -> JudgeResult:
        try:
            with open(self.path, encoding="utf-8") as f:
                doc = json.load(f)
        except OSError as e:
            raise Refusal(ToolError(code="JUDGE_UNAVAILABLE", message=f"Fixture file not readable: {e}", field="judge")) from e
        entry = doc.get("results", {}).get(rubric.id)
        if entry is None:
            raise Refusal(ToolError(code="JUDGE_UNAVAILABLE", message=f"Fixture has no result for rubric '{rubric.id}'.", field="rubric_id"))
        return JudgeResult.model_validate(entry)


JUDGE_SYSTEM = (
    "You are a strict rubric judge. Score each criterion from 0 to 1 using only the item and the context given. "
    "Never invent facts. Return JSON only: {\"scores\": [{\"criterion\": id, \"score\": number, \"note\": string}], \"notes\": string}."
)


class ClaudeJudge:
    name: Literal["deterministic", "claude", "fixture"] = "claude"

    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.environ.get("G0_JUDGE_MODEL") or DEFAULT_JUDGE_MODEL
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise Refusal(ToolError(code="JUDGE_UNAVAILABLE", message="No ANTHROPIC_API_KEY in the environment; use judge 'deterministic' or 'fixture'.", field="judge",
                                    next=NextStep(tool="evaluation", why="call again with judge='deterministic'")))
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover
            raise Refusal(ToolError(code="JUDGE_UNAVAILABLE", message="The `anthropic` package is not installed (pip install 'g0-shared-layer[judge]').", field="judge")) from e
        self._client = anthropic.Anthropic()
        return self._client

    def judge(self, db: Database, rubric: Rubric, item: str | dict[str, Any], context: str | None, run_id: str | None) -> JudgeResult:
        rid = run_id or "evaluation"
        cap = observability.cap_usd()
        total_before = observability.run_total(db, rid)
        if total_before.cost_usd >= cap:
            raise Refusal(ToolError(code="OVER_CAP", message=f"Run '{rid}' has spent ${total_before.cost_usd:.4f} of the ${cap:.2f} cap; no more model calls.", field="run_id",
                                    next=NextStep(tool="observability", why="read the run total")))
        if self.model not in PRICES_PER_MTOK:
            raise Refusal(ToolError(code="JUDGE_UNAVAILABLE", message=f"No price on file for model '{self.model}'; add it to PRICES_PER_MTOK after confirming it on Anthropic's pricing page.", field="judge"))
        client = self._get_client()
        prompt = {
            "rubric": {"id": rubric.id, "title": rubric.title, "criteria": [{"id": c["id"], "description": c["description"]} for c in rubric.criteria]},
            "item": item,
            "context": context,
        }
        msg = client.messages.create(
            model=self.model, max_tokens=1500, system=JUDGE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}],
        )
        in_tok = int(getattr(msg.usage, "input_tokens", 0))
        out_tok = int(getattr(msg.usage, "output_tokens", 0))
        p_in, p_out = PRICES_PER_MTOK[self.model]
        cost = round(in_tok * p_in / 1e6 + out_tok * p_out / 1e6, 6)
        observability.run(db, observability.Input(run_id=rid, agent="evaluation", step=f"judge:{rubric.id}", model=self.model,
                                                  input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost, status="ok"))
        text = "".join(getattr(b, "text", "") for b in msg.content)
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise Refusal(ToolError(code="JUDGE_UNAVAILABLE", message="The model did not return JSON.", field="judge"))
        parsed = json.loads(m.group(0))
        by_id = {s["criterion"]: s for s in parsed.get("scores", [])}
        scores = []
        for c in rubric.criteria:
            s = by_id.get(c["id"], {})
            scores.append(CriterionScore(criterion=c["id"], score=max(0.0, min(1.0, float(s.get("score", 0)))), weight=float(c.get("weight", 1)),
                                         required=bool(c.get("required", False)), note=str(s.get("note", "not scored by the model"))))
        return JudgeResult(scores=scores, notes=str(parsed.get("notes", "")), usage=Usage(model=self.model, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost))


def pick_judge(name: JudgeName) -> Judge:
    if name == "deterministic":
        return DeterministicJudge()
    if name == "fixture":
        return FixtureJudge()
    if name == "claude":
        return ClaudeJudge()
    return ClaudeJudge() if os.environ.get("ANTHROPIC_API_KEY") else DeterministicJudge()


def run(db: Database, inp: Input, judge: Judge | None = None) -> Output:
    rubric = load_rubric(db, inp.rubric_id)
    j = judge or pick_judge(inp.judge)
    result = j.judge(db, rubric, inp.item, inp.context, inp.run_id)
    total, passed = decide(rubric, result.scores)
    eid = new_id("eval")
    out = Output(evaluation_id=eid, rubric_id=rubric.id, judge=j.name, scores=result.scores, total=total, passed=passed, notes=result.notes, usage=result.usage)
    with db.conn:
        db.conn.execute("INSERT INTO evaluations (evaluation_id, rubric_id, judge, item, result, evaluated_at) VALUES (?,?,?,?,?,?)",
                        (eid, rubric.id, j.name, _item_text(inp.item), out.model_dump_json(), now_iso()))
    return out
