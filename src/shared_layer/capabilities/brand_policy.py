"""brand.policy v1 — does this text break a seeded brand rule? (D-7, D-16)

A rule engine over `brand_rules`. Four rule kinds: phrase, regex, max_words,
max_sentences. Judgment ("never hype", "never a pitch") is the evaluation
capability's job, not this one's.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared_layer.errors import NextStep, Refusal, ToolError
from shared_layer.storage import Database
from shared_layer.text import sentences, word_count

CAPABILITY = "brand.policy"
TOOL = "brand_policy"
VERSION = "1"
DESCRIPTION = (
    "Check text against the shared brand policy (never-use phrases, emoji, beginner voice; on channel "
    "`post_angle` also one sentence and at most 25 words). Returns pass/fail and every violation with the "
    "rule id, the excerpt that tripped it and a fix. Deterministic; it does not judge tone or hype — call "
    "`evaluation` with rubric `post_angle_v1` for that."
)

Channel = Literal["linkedin", "email", "digest", "post_angle", "other"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    text: str = Field(min_length=1, description="The text to check.")
    channel: Channel = Field(description="Where the text will go; some rules apply to one channel only.")
    policy_version: str = Field(default="1", description="Which brand policy version to apply.")


class Violation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Literal["fail", "warn"]
    excerpt: str = Field(description="The text that tripped the rule.")
    fix: str


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    capability: Literal["brand.policy"] = "brand.policy"
    ok: bool = True
    error: ToolError | None = None
    policy_version: str = ""
    channel: str = ""
    passed: bool = Field(default=False, description="True when no `fail` violation was found.")
    violations: list[Violation] = Field(default_factory=list)
    rules_checked: int = 0


def _rules(db: Database, policy_version: str) -> list[dict]:
    rows = db.conn.execute("SELECT * FROM brand_rules WHERE policy_version = ? ORDER BY id", (policy_version,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["channels"] = json.loads(d["channels"])
        out.append(d)
    return out


def _excerpt(text: str, start: int, end: int, pad: int = 20) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return ("…" if s > 0 else "") + text[s:e].replace("\n", " ") + ("…" if e < len(text) else "")


def apply_rules(text: str, channel: str, rules: list[dict]) -> list[Violation]:
    violations: list[Violation] = []
    for r in rules:
        if "*" not in r["channels"] and channel not in r["channels"]:
            continue
        kind = r["kind"]
        if kind == "phrase":
            for m in re.finditer(re.escape(r["pattern"]), text, re.IGNORECASE):
                violations.append(Violation(rule_id=r["id"], severity=r["severity"], excerpt=_excerpt(text, m.start(), m.end()), fix=r["fix"]))
        elif kind == "regex":
            for m in re.finditer(r["pattern"], text, re.IGNORECASE):
                violations.append(Violation(rule_id=r["id"], severity=r["severity"], excerpt=_excerpt(text, m.start(), m.end()), fix=r["fix"]))
        elif kind == "max_words":
            n = word_count(text)
            if n > r["limit"]:
                violations.append(Violation(rule_id=r["id"], severity=r["severity"], excerpt=f"{n} words", fix=r["fix"]))
        elif kind == "max_sentences":
            n = len(sentences(text))
            if n > r["limit"]:
                violations.append(Violation(rule_id=r["id"], severity=r["severity"], excerpt=f"{n} sentences", fix=r["fix"]))
    return violations


def run(db: Database, inp: Input) -> Output:
    policy = db.conn.execute("SELECT * FROM brand_policies WHERE policy_version = ?", (inp.policy_version,)).fetchone()
    if policy is None:
        known = [r[0] for r in db.conn.execute("SELECT policy_version FROM brand_policies ORDER BY policy_version")]
        raise Refusal(ToolError(code="UNKNOWN_POLICY", message=f"No brand policy version '{inp.policy_version}'. Known: {known}.",
                                field="policy_version", next=NextStep(tool="health", why="lists the seeded policy versions")))
    rules = _rules(db, inp.policy_version)
    violations = apply_rules(inp.text, inp.channel, rules)
    return Output(policy_version=inp.policy_version, channel=inp.channel,
                  passed=not any(v.severity == "fail" for v in violations), violations=violations, rules_checked=len(rules))
