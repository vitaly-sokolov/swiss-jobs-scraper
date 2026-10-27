from __future__ import annotations

import html
import re
import unicodedata

_TAGS = re.compile(r"<(script|style)\b.*?</\1>|<[^>]+>", re.S | re.I)  # inline tags: removed
_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|td|section)\b[^>]*>", re.I)
_WS = re.compile(r"[ \t\r\f\v]+")

# Gender / workload markers that vary between boards for the same ad.
_TITLE_NOISE = re.compile(
    r"\((?:[mwfdxhak]\s*[/|,]\s*)+[mwfdxhak]\)"     # (m/w/d), (f/m/x), (h/f)
    r"|\b[mwfdxh](?:\s*/\s*[mwfdxh]){1,3}\b"        # m/w/d without brackets
    r"|\(?\d{2,3}\s*(?:-|–|bis|à)?\s*\d{0,3}\s*%\)?"  # 80-100%, 100 %
    r"|\(all genders?\)|\(\*\)|\*in\b|:in\b",
    re.I,
)
_NON_WORD = re.compile(r"[^\w+#.]+", re.U)


def html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = _BLOCK.sub("\n", value)
    text = _TAGS.sub("", text)
    text = html.unescape(text)
    lines = [_WS.sub(" ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def fold(value: str) -> str:
    """Lowercase and strip accents: 'Zürich' → 'zurich', 'Genève' → 'geneve'."""
    value = value.replace("ß", "ss")
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def normalize_title(title: str) -> str:
    cleaned = _TITLE_NOISE.sub(" ", title)
    cleaned = _NON_WORD.sub(" ", fold(cleaned))
    return " ".join(cleaned.split())


_LEGAL = re.compile(r"\b(ag|sa|gmbh|sarl|s\.?a\.?r\.?l|ltd|llc|inc|plc|se|kg|co|corp|group|holding|schweiz|suisse|switzerland)\b\.?")


def normalize_company(company: str | None) -> str:
    if not company:
        return ""
    value = _LEGAL.sub(" ", fold(company))
    return " ".join(_NON_WORD.sub(" ", value).split())
