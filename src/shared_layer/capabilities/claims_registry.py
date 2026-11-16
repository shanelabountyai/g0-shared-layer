"""claims.registry v1 — is this number or statement backed by a source we have? (D-15)

Deterministic, no model call. A claim is `supported` only when EVERY statistic
in it is backed by a registry fact for the same metric (D-23): the same
normalized number, in a row that shares topic words or a whole-word key phrase
with the claim, and not out-scored by a different figure of that row whose
clause fits the claim's clause better (that is a contradiction). Sample sizes
cited with their own noun ("1,993 respondents") and offer/price figures ("save
15%", "$499/mo", D-24) are not statistics: they neither back nor block a claim.
"""

from __future__ import annotations

import json
import re
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared_layer.errors import ToolError
from shared_layer.storage import Database
from shared_layer.text import normalized_numbers, number_spans, sentences, topic_words

CAPABILITY = "claims.registry"
TOOL = "claims_registry"
VERSION = "1"
DESCRIPTION = (
    "Check claims against the shared claims registry (the verified stats every agent may use). "
    "Give `text` (sentences carrying a statistic are extracted) or a `claims` list. Each claim comes back "
    "`supported` with its source only when EVERY statistic in it matches a registry stat for the same metric; "
    "`unsupported` when any number contradicts or is missing from a registry row the claim speaks to; "
    "`needs_source` when the registry says nothing about it. Sample sizes are not statistics. Offer and "
    "price figures (\"save 15%\", \"$499/mo\") are not checked: an offer-only claim is `supported` with no "
    "source. Use before publishing any number. Does not search the web; a `needs_source` claim needs a "
    "human or a new registry row, not a retry."
)

# A claim must share at least this many topic words with a registry entry
# before a number comparison means anything.
MIN_TOPIC_OVERLAP = 2


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1"] = Field(default="1", description="Contract version.")
    text: str | None = Field(default=None, description="Free text; sentences carrying a number other than an offer/price figure are checked as claims.")
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
    source: Source | None = Field(default=None, description="The matching registry row; for `unsupported`, the row the claim contradicts or speaks to. Null for `needs_source` and for an offer-only claim.")
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
    # A sentence is a claim when it carries a number that is not an offer/price figure (D-24).
    return [s for s in sentences(inp.text) if any(f.kind != "offer" for f in _figures(s, []))]


# -- parsing helpers ---------------------------------------------------------

# Clause boundaries: a number's metric is read from its clause, not the whole sentence.
_CLAUSE_BREAK = re.compile(
    r";|:\s|,\s|[()]|\s[-–—]\s|\bbut\b|\bwhile\b|\bwhereas\b"
    r"|\band\s+(?=(?:(?:only|just|over|under|nearly|about|almost|roughly|around)\s+)?[~$≈]?\d)",
    re.IGNORECASE,
)
_SAMPLE_COUNT = re.compile(r"[~≈]?(\d{1,3}(?:,\d{3})+|\d+)\s+([A-Za-z]+)")
_NEXT_WORD = re.compile(r"\s*([A-Za-z]+)")
# Offer / price cues (D-24): a figure next to one of these is a commercial term, not a market statistic.
_OFFER_BEFORE = frozenset({"save", "saving", "extra", "discount", "coupon", "promo", "code", "price", "priced",
                           "pricing", "fee", "deposit"})
_OFFER_AFTER = re.compile(
    r"\s*(?:off\b|discount|savings|cashback|rebate|/\s*(?:mo|month|yr|year|seat|user)\b"
    r"|per\s+(?:month|year|seat|user)\b|a\s+month\b)",
    re.IGNORECASE,
)


_TERM_UNIT = re.compile(r"\s*(?:days?|weeks?|months?|years?|seats?|users?)\b", re.IGNORECASE)


class _Fact(NamedTuple):
    number: str
    context: frozenset[str]


class _Figure(NamedTuple):
    number: str
    kind: str  # "stat" | "sample" | "offer"
    context: frozenset[str]


def _clauses(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _CLAUSE_BREAK.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _clause_of(spans: list[tuple[int, int]], pos: int) -> tuple[int, int]:
    for s, e in spans:
        if s <= pos < e:
            return s, e
    return 0, 0


def _value(number: str) -> str:
    return re.sub(r"[^\d.]", "", number)


def _phrase_hit(phrase: str, low: str) -> bool:
    """Whole-word / phrase-boundary match: 'future-built' does not match inside 'nonfuture-builtin'."""
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])", low) is not None


def _sample_counts(rows: list[dict]) -> set[tuple[str, str]]:
    out = set()
    for r in rows:
        out |= r["sample_counts"]
    return out


def _figures(text: str, rows: list[dict]) -> list[_Figure]:
    """Classify every number in `text`: `offer` (a price/discount term, D-24), `sample` (a registry
    row's sample size cited with its own noun, e.g. '1,993 respondents'), else `stat`."""
    samples = _sample_counts(rows)
    clauses = _clauses(text)
    out: list[_Figure] = []
    spans = number_spans(text)
    for number, start, end in spans:
        cs, ce = _clause_of(clauses, start)
        before = re.findall(r"[a-z]+", text[cs:start].lower())[-2:]
        after = text[end:ce]
        context = frozenset(topic_words(text[cs:ce]))
        if (set(before) & _OFFER_BEFORE and (number.endswith("%") or number.startswith("$"))) or _OFFER_AFTER.match(after):
            out.append(_Figure(number, "offer", context))
            continue
        nxt = _NEXT_WORD.match(text[end:])
        if nxt and number.isdigit():
            noun = nxt.group(1).lower()
            if any(n == number and noun[:5] == sn[:5] for n, sn in samples):
                out.append(_Figure(number, "sample", context))
                continue
        out.append(_Figure(number, "stat", context))
    # A bare term length next to an offer in the same clause ("$499/mo for 12 months") is part of the offer.
    for i, f in enumerate(out):
        if f.kind == "stat" and f.number.isdigit() and any(g.kind == "offer" and g.context == f.context for g in out):
            if _TERM_UNIT.match(text[spans[i][2]:]):
                out[i] = f._replace(kind="offer")
    return out


def _rows(db: Database) -> list[dict]:
    rows = []
    for r in db.conn.execute("SELECT * FROM claims ORDER BY id"):
        d = dict(r)
        d["key_phrases"] = json.loads(d["key_phrases"])
        # Only the stat's own numbers can back a claim; the sample size never does (D-23).
        d["numbers"] = normalized_numbers(d["stat"])
        stat = d["stat"]
        clauses = _clauses(stat)
        facts = []
        for number, start, _ in number_spans(stat):
            cs, ce = _clause_of(clauses, start)
            facts.append(_Fact(number, frozenset(topic_words(stat[cs:ce]))))
        d["facts"] = facts
        d["sample_counts"] = {
            (n, noun.lower()) for raw, noun in _SAMPLE_COUNT.findall(d["sample"]) for n in normalized_numbers(raw)
        }
        d["topics"] = topic_words(d["stat"]) | topic_words(d["title"])
        rows.append(d)
    return rows


def _source(r: dict) -> Source:
    return Source(registry_id=r["id"], publisher=r["publisher"], title=r["title"], sample=r["sample"], url=r["url"], stat=r["stat"])


def check_claim(claim: str, rows: list[dict]) -> ClaimResult:
    """D-15 as amended by D-23/D-24: every statistic in the claim must be backed by a registry
    fact for the same metric; sample sizes and offer/price figures are not statistics."""
    low = claim.lower()
    topics = topic_words(claim)
    phrase_hits = [(r, p) for r in rows for p in r["key_phrases"] if p and _phrase_hit(p, low)]
    gated: dict[str, dict] = {r["id"]: r for r in rows if len(topics & r["topics"]) >= MIN_TOPIC_OVERLAP}
    for r, _ in phrase_hits:
        gated.setdefault(r["id"], r)

    figures = _figures(claim, rows)
    stats = [f for f in figures if f.kind == "stat"]
    ignored = [f"{f.number} ({f.kind})" for f in figures if f.kind != "stat"]
    ignored_note = f" Not checked as statistics: {', '.join(ignored)}." if ignored else ""

    if not stats:
        if phrase_hits:
            r, phrase = phrase_hits[0]
            return ClaimResult(claim=claim, status="supported", matched_on="phrase", source=_source(r),
                               note=f"Matches registry phrase '{phrase}'.{ignored_note}")
        if figures and all(f.kind == "offer" for f in figures):
            return ClaimResult(claim=claim, status="supported", matched_on="none", source=None,
                               note=f"No market or research statistic to check: {', '.join(f.number for f in figures)} "
                                    "are offer/price figures, which the registry does not govern (D-24).")
        return ClaimResult(claim=claim, status="needs_source", matched_on="none", source=None,
                           note=f"No registry row speaks to this claim. Find a primary source or leave the number out.{ignored_note}")

    claim_values = {_value(f.number) for f in stats}
    backed: list[tuple[str, dict]] = []
    contradicted: list[tuple[str, dict, str]] = []
    unbacked: list[str] = []
    for f in stats:
        ok_row, rival = None, None
        for r in gated.values():
            own = [x for x in r["facts"] if x.number == f.number]
            if not own:
                continue
            own_best = max(len(f.context & x.context) for x in own)
            rivals = [x for x in r["facts"] if _value(x.number) not in claim_values]
            top = max(rivals, key=lambda x: len(f.context & x.context), default=None)
            if top is not None and len(f.context & top.context) > own_best:
                rival = rival or (r, top.number)
                continue
            ok_row = r
            break
        if ok_row is not None:
            backed.append((f.number, ok_row))
        elif rival is not None:
            contradicted.append((f.number, rival[0], rival[1]))
        else:
            unbacked.append(f.number)

    matched_on: str
    if not contradicted and not unbacked:
        phrase_ids = {r["id"] for r, _ in phrase_hits}
        src = next((r for _, r in backed if r["id"] in phrase_ids), backed[0][1])
        per = "; ".join(f"{n} → {r['id']}" for n, r in backed)
        return ClaimResult(claim=claim, status="supported", matched_on="phrase" if phrase_hits else "number",
                           source=_source(src), note=f"Every statistic is backed by a registry row for the same metric: {per}.{ignored_note}")

    if not gated:
        return ClaimResult(claim=claim, status="needs_source", matched_on="none", source=None,
                           note=f"No registry row speaks to this claim. Find a primary source or leave the number out.{ignored_note}")

    parts = []
    if contradicted:
        parts.append("; ".join(f"{n} contradicts {r['publisher']}'s figure {m} for that metric" for n, r, m in contradicted))
    if unbacked:
        parts.append(f"number(s) {unbacked} are not in any matching registry row")
    if backed:
        parts.append(f"backed: {', '.join(n for n, _ in backed)}")
    if contradicted:
        src, matched_on = contradicted[0][1], "number"
    elif phrase_hits:
        src, matched_on = phrase_hits[0][0], "phrase"
    else:
        src = max(gated.values(), key=lambda r: len(topics & r["topics"]))
        matched_on = "number" if backed else "topic"
    if phrase_hits and matched_on != "number":
        matched_on = "phrase"
    return ClaimResult(claim=claim, status="unsupported", matched_on=matched_on, source=_source(src),  # type: ignore[arg-type]
                       note="Every statistic must be backed by the registry for the same metric: " + "; ".join(parts)
                            + f". Check the wording against the source before use.{ignored_note}")


def run(db: Database, inp: Input) -> Output:
    rows = _rows(db)
    claims = extract_claims(inp)
    return Output(results=[check_claim(c, rows) for c in claims], registry_size=len(rows))
