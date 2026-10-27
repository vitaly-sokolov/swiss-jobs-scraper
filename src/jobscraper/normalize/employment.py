from __future__ import annotations

import re

from jobscraper.normalize.text import fold

_INTERNSHIP = re.compile(r"\b(intern|internship|praktik\w*|stage|stagiaire|werkstudent\w*|working student|lehrstelle|apprenti\w*|lernende\w*|volontariat)\b")
_CONTRACT = re.compile(r"\b(contract|contractor|freelanc\w*|temporar\w*|temporär|temporaire|befristet|mandat|interim|cdd|auf zeit)\b")
_PART_TIME = re.compile(r"\b(part[- ]time|teilzeit|temps partiel|nebenerwerb)\b")
_FULL_TIME = re.compile(r"\b(full[- ]time|vollzeit|temps plein|full_time)\b")
# Permanent contract words say nothing about workload; used only as a last resort.
_PERMANENT = re.compile(r"\b(festanstellung|unbefristet|permanent|cdi)\b")
_PERCENT = re.compile(r"(\d{2,3})\s*%")


def employment_type(employment_text: str | None, title: str = "") -> str:
    """full_time | part_time | contract | internship | unknown."""
    text = fold(" ".join(t for t in (employment_text, title) if t))
    if _INTERNSHIP.search(text):
        return "internship"
    if _CONTRACT.search(text):
        return "contract"
    percents = [int(p) for p in _PERCENT.findall(text) if 0 < int(p) <= 100]
    if percents:
        return "full_time" if max(percents) >= 80 else "part_time"
    if _PART_TIME.search(text):
        return "part_time"
    if _FULL_TIME.search(text) or _PERMANENT.search(text):
        return "full_time"
    return "unknown"
