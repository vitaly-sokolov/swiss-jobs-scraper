from __future__ import annotations

import re
from collections.abc import Iterable

from jobscraper.normalize.text import fold


def _alias_pattern(alias: str) -> re.Pattern[str]:
    escaped = re.escape(fold(alias))
    # Word boundaries that also work for tokens like "c#", "c++", ".net", "node.js".
    return re.compile(rf"(?<![\w+#.]){escaped}(?![\w+#])")


class Tagger:
    """Map text and source-provided technology lists to canonical tags."""

    def __init__(self, vocabulary: dict[str, list[str]]) -> None:
        self._patterns: list[tuple[str, list[re.Pattern[str]]]] = [
            (tag, [_alias_pattern(a) for a in [tag, *(aliases or [])]])
            for tag, aliases in vocabulary.items()
        ]

    def tags(self, *texts: str | None, provided: Iterable[str] = ()) -> list[str]:
        haystack = fold(" \n ".join(t for t in texts if t))
        provided_text = fold(" | ".join(provided))
        found: list[str] = []
        for tag, patterns in self._patterns:
            if any(p.search(provided_text) or p.search(haystack) for p in patterns):
                found.append(tag)
        return found
