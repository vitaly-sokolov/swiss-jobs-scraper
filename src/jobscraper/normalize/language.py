"""Tiny stopword-based detector for de / fr / en (D6 keeps all three)."""

from __future__ import annotations

import re

_STOPWORDS = {
    "de": set("und der die das mit für wir sie ist ein eine zu von auf im den des bei als oder unsere ihre deine du bist nicht werden sind auch".split()),
    "fr": set("et le la les des une un pour vous nous est du au aux avec sur dans votre vos notre nos être qui que en sont".split()),
    "en": set("and the to of for with you we are is in our your a an on as be will this that at from team".split()),
}
_WORD = re.compile(r"[a-zA-ZÀ-ÿ']+")


def detect_language(text: str | None, min_hits: int = 3) -> str | None:
    """de | fr | en | other, or None when the text is too short to tell."""
    if not text:
        return None
    words = _WORD.findall(text[:5000].lower())
    counts = {lang: sum(w in stop for w in words) for lang, stop in _STOPWORDS.items()}
    ranked = sorted(counts, key=counts.__getitem__, reverse=True)
    best, second = ranked[0], ranked[1]
    if counts[best] >= min_hits and counts[best] > counts[second]:
        return best
    return "other" if len(words) >= 40 else None
