"""claims.registry v1 — is this number or statement backed by a source we have? (D-15)

Deterministic: normalized-number match plus topic overlap, or a key-phrase
match, against the seeded registry. No model call.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared_layer.errors import ToolError
from shared_layer.storage import Database
from shared_layer.text import normalized_numbers, sentences, topic_words

CAPABILITY = "claims.registry"
TOOL = "claims_registry"
VERSION = "1"
DESCRIPTION = (
    "Check claims against the shared claims registry (the verified stats every agent may use). "
    "Give `text` (quantitative sentences are extracted) or a `claims` list. Each claim comes back "
    "`supported` with its source, `unsupported` (contradicts a registry stat), or `needs_source` "
    "(the registry says nothing about it). Use before publishing any number. Does not search the web; "
    "a `needs_source` claim needs a human or a new registry row, not a retry."
)

# A claim must share at least this many topic words with a registry entry
# before a number comparison means anything.
MIN_TOPIC_OVERLAP = 2


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = Field(default="1", description="Contract version.")
    text: str | None = Field(default=None, description="Free text; sentences carrying a number are checked as claims.")
    claims: list[str] | None = Field(default=None, description="Claims to check one by one.")

    @model_validator(mode="after")
    def _one_of(self) -> Input:
        if not (self.text and self.text.strip()) and not self.claims:
            raise ValueError("give `text` or a non-empty `claims` list")
        return self


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_id: str
    publisher: str
    title: str
    sample: str = Field(description="Sample size and date, as the registry records them.")
    url: str
    stat: str = Field(description="The registry's wording of the stat.")


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim: str
    status: Literal["supported", "unsupported", "needs_source"]
    matched_on: Literal["number", "phrase", "topic", "none"]
    source: Source | None = Field(default=None, description="The matching registry row; for `unsupported`, the row the claim contradicts.")
    note: str


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = "1"
    capability: Literal["claims.registry"] = "claims.registry"
    ok: bool = True
    error: ToolError | None = None
    results: list[ClaimResult] = Field(default_factory=list)
    registry_size: int = 0


def extract_claims(inp: Input) -> list[str]:
    if inp.claims:
        return [c.strip() for c in inp.claims if c and c.strip()]
    assert inp.text is not None
    return [s for s in sentences(inp.text) if normalized_numbers(s)]


def _rows(db: Database) -> list[dict]:
    rows = []
    for r in db.conn.execute("SELECT * FROM claims ORDER BY id"):
        d = dict(r)
        d["key_phrases"] = json.loads(d["key_phrases"])
        d["numbers"] = normalized_numbers(d["stat"])
        d["topics"] = topic_words(d["stat"]) | topic_words(d["title"])
        rows.append(d)
    return rows


def _source(r: dict) -> Source:
    return Source(registry_id=r["id"], publisher=r["publisher"], title=r["title"], sample=r["sample"], url=r["url"], stat=r["stat"])


def check_claim(claim: str, rows: list[dict]) -> ClaimResult:
    low = claim.lower()
    nums = normalized_numbers(claim)
    topics = topic_words(claim)

    # 1. key phrase → supported outright (the phrase identifies the stat)
    for r in rows:
        for phrase in r["key_phrases"]:
            if phrase and phrase in low:
                if nums and not (nums & r["numbers"]) and r["numbers"]:
                    return ClaimResult(claim=claim, status="unsupported", matched_on="phrase", source=_source(r),
                                       note=f"Names the {r['publisher']} stat but its number(s) {sorted(nums)} are not in the registry row {sorted(r['numbers'])}.")
                return ClaimResult(claim=claim, status="supported", matched_on="phrase", source=_source(r),
                                   note=f"Matches registry phrase '{phrase}'.")

    # 2. number + topic overlap → supported; topic overlap with a different number → unsupported
    best: tuple[int, dict] | None = None
    for r in rows:
        overlap = len(topics & r["topics"])
        if overlap < MIN_TOPIC_OVERLAP:
            continue
        shared = nums & r["numbers"]
        if shared:
            return ClaimResult(claim=claim, status="supported", matched_on="number", source=_source(r),
                               note=f"Number(s) {sorted(shared)} match the registry row on {overlap} shared topic words.")
        if best is None or overlap > best[0]:
            best = (overlap, r)

    if best is not None and nums:
        overlap, r = best
        return ClaimResult(claim=claim, status="unsupported", matched_on="topic", source=_source(r),
                           note=f"Shares {overlap} topic words with the {r['publisher']} row but its number(s) {sorted(nums)} are not that row's {sorted(r['numbers'])}. Check the wording against the source before use.")

    return ClaimResult(claim=claim, status="needs_source", matched_on="none", source=None,
                       note="No registry row speaks to this claim. Find a primary source or leave the number out.")


def run(db: Database, inp: Input) -> Output:
    rows = _rows(db)
    claims = extract_claims(inp)
    return Output(results=[check_claim(c, rows) for c in claims], registry_size=len(rows))
