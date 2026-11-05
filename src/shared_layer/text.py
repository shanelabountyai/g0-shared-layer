"""Small, deterministic text helpers shared by claims.registry, brand.policy and
the deterministic judge. No model calls here, ever."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[~$])|\n+")
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-$%+.,]*")
_NUMBER = re.compile(
    r"(?P<prefix>[~$≈]?)(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?P<suffix>%|x|k|m|b|\+)?(?P<pct_word>\s*percent)?",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s)\]>\"']+")
_QUOTE = re.compile(r"[\"“”]([^\"“”]{8,})[\"“”]")

STOPWORDS = frozenset(
    """a an the and or of to in on for from by with as at is are was were be been being this that these those
    it its their there here than then so such only any all most more less very not no nor but if into over
    under up down out off about after before between during through while who whom which what when where why
    how do does did done have has had having will would can could should may might must shall say says said
    get got one two three four five six seven eight nine ten per cent percent org orgs company companies
    report reports found finds study survey year years""".split()
)


def sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p and p.strip()]
    return parts


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


def normalized_numbers(text: str) -> set[str]:
    """Numbers as the registry compares them: `88%`, `88 percent` → `88%`;
    `1,993` → `1993`; `$100M` → `$100m`; `3x` → `3x`; `~6%` → `6%`; `5%+` → `5%`.
    Years (1900–2099) are dropped: they are dates, not statistics."""
    out: set[str] = set()
    for m in _NUMBER.finditer(text):
        num = m.group("num").replace(",", "")
        suffix = (m.group("suffix") or "").lower()
        if m.group("pct_word"):
            suffix = "%"
        if suffix == "+":
            suffix = ""
        prefix = "$" if m.group("prefix") == "$" else ""
        if not prefix and not suffix and num.isdigit() and 1900 <= int(num) <= 2099:
            continue
        try:
            value = float(num)
        except ValueError:
            continue
        canonical = f"{int(value)}" if value.is_integer() else f"{value:g}"
        out.add(f"{prefix}{canonical}{suffix}")
    return out


def topic_words(text: str) -> set[str]:
    words = set()
    for w in re.findall(r"[A-Za-z][A-Za-z\-]+", text.lower()):
        w = w.strip("-")
        if len(w) >= 3 and w not in STOPWORDS:
            words.add(w)
    return words


def urls(text: str) -> set[str]:
    return set(_URL.findall(text))


def quotes(text: str) -> list[str]:
    return [q.strip() for q in _QUOTE.findall(text)]


def has_number_or_proper_noun(text: str) -> bool:
    if normalized_numbers(text):
        return True
    # a capitalised word that is not the first word of a sentence
    for s in sentences(text):
        words = s.split()
        if any(w[:1].isupper() and w[1:2].islower() for w in words[1:]):
            return True
    return False


HYPE_WORDS = (
    "revolutionary", "revolutionize", "unlock", "unleash", "supercharge", "next-level", "mind-blowing",
    "incredible", "amazing", "disrupt", "disruptive", "10x your", "seamless", "cutting-edge", "world-class",
    "thrilled", "delighted to announce", "reach out", "dm me", "link in bio",
)


def hype_hits(text: str) -> list[str]:
    low = text.lower()
    return [w for w in HYPE_WORDS if w in low]
