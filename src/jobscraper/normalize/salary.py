"""Parse *published* salary text only (D11). Unparseable → all None; text is kept."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

_CURRENCY = re.compile(r"\b(CHF|EUR|USD|GBP|Fr\.?|SFr\.?)|([€$£])", re.I)
_CURRENCY_MAP = {"chf": "CHF", "fr": "CHF", "fr.": "CHF", "sfr": "CHF", "sfr.": "CHF",
                 "eur": "EUR", "€": "EUR", "usd": "USD", "$": "USD", "gbp": "GBP", "£": "GBP"}

# 110'000 · 110’000 · 110 000 · 110,000 · 110.000 · 110000 · 110k · 1.5k · 95.50
_NUMBER = re.compile(r"(\d{1,3}(?:['’ ,. ]\d{3})+|\d+(?:[.,]\d+)?)\s*(k|K|tsd\.?|Tsd\.?)?(?![\d%])")

_PERIODS = [
    ("hour", re.compile(r"(/\s*h\b|per hour|hourly|pro stunde|stundenlohn|/\s*std|par heure|de l'heure|\bhour\b)", re.I)),
    ("day", re.compile(r"(/\s*(day|tag|jour)\b|per day|daily|pro tag|tagessatz|par jour|\bday\b)", re.I)),
    ("month", re.compile(r"(/\s*(month|monat|mois)\b|per month|monthly|pro monat|monatlich|par mois|\bmonth\b)", re.I)),
    ("year", re.compile(r"(/\s*(year|jahr|an)\b|per year|annual|yearly|p\.?\s?a\.?|pro jahr|jährlich|par an|annuel|brutto|\byear\b)", re.I)),
]


@dataclass(frozen=True)
class Salary:
    min: Decimal | None = None
    max: Decimal | None = None
    currency: str | None = None
    period: str | None = None


def _to_decimal(raw: str, suffix: str | None) -> Decimal | None:
    s = raw.replace(" ", " ")
    if re.fullmatch(r"\d{1,3}(?:['’ ,.]\d{3})+", s):
        s = re.sub(r"['’ ,.]", "", s)
    else:
        s = s.replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    if suffix:
        value *= 1000
    return value


def parse_salary(text: str | None) -> Salary:
    if not text:
        return Salary()
    numbers = [n for m in _NUMBER.finditer(text) if (n := _to_decimal(m.group(1), m.group(2))) is not None]
    numbers = [n for n in numbers if n > 0]
    if not numbers:
        return Salary()
    lo, hi = numbers[0], numbers[1] if len(numbers) > 1 else numbers[0]
    if hi < lo:
        lo, hi = hi, lo
    currency = None
    if m := _CURRENCY.search(text):
        currency = _CURRENCY_MAP.get((m.group(1) or m.group(2)).lower())
    period = next((name for name, pattern in _PERIODS if pattern.search(text)), None)
    if period is None:
        period = _infer_period(hi)
    if not _plausible(lo, hi, period):
        return Salary()
    return Salary(lo.quantize(Decimal("0.01")), hi.quantize(Decimal("0.01")), currency or "CHF", period)


def _infer_period(value: Decimal) -> str | None:
    if value >= 20_000:
        return "year"
    if value >= 2_000:
        return "month"
    if value >= 300:
        return "day"
    if value >= 20:
        return "hour"
    return None


_RANGES = {"year": (10_000, 2_000_000), "month": (1_000, 200_000), "day": (100, 10_000), "hour": (10, 1_000)}


def _plausible(lo: Decimal, hi: Decimal, period: str | None) -> bool:
    if period is None:
        return False
    low, high = _RANGES[period]
    return low <= lo and hi <= high
