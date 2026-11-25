"""Synthetic exchange rates published by a fictitious provider ("HALCYON-FX", ECB-style).

Convention: ``exchange_rate`` = units of TARGET currency per ONE unit of SOURCE currency.
Published rates are EUR-based (source_currency = EUR) for business days. Cross and inverse rates are
triangulated by consumers (generator and warehouse) through EUR with identical precision rules.

Injected source-quality scenarios (fed to the warehouse, not used internally):
* a re-published correction (same rate_date, later publication_timestamp) – latest valid wins,
* an invalid zero rate publication – must be quarantined, never used,
* one missing business day for INR – covered by the max spot lookback rule.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from data_generator.core import at, period_of, rng_for
from finance_common.money import (
    PUBLISHED_RATE_PRECISION,
    MissingExchangeRateError,
    cross_rate,
    round_rate,
)

START_LEVELS = {  # EUR -> X at the start of the simulation
    "USD": 1.2200, "GBP": 0.8990, "CHF": 1.0800, "SEK": 10.0800, "JPY": 126.30,
    "SGD": 1.6200, "INR": 89.50, "CAD": 1.5600, "CNY": 7.9600,
}
ANNUAL_VOL = {"USD": 0.075, "GBP": 0.06, "CHF": 0.05, "SEK": 0.06, "JPY": 0.09, "SGD": 0.05, "INR": 0.07,
              "CAD": 0.07, "CNY": 0.06}
DRIFT = {"USD": -0.025, "GBP": 0.01, "CHF": -0.025, "SEK": 0.012, "JPY": 0.035, "SGD": -0.01, "INR": 0.025,
         "CAD": -0.01, "CNY": -0.01}
MAX_LOOKBACK_DAYS = 5


class FxEngine:
    def __init__(self, seed: int, start: date, end: date) -> None:
        self.start, self.end = start, end
        self.eur: dict[tuple[date, str], Decimal] = {}  # EUR->X spot for business days
        self.published: list[dict] = []
        rng = rng_for(seed, "fx")
        level = dict(START_LEVELS)
        d = start - timedelta(days=10)  # small pre-history so early weekend lookups succeed
        dt = 1 / 260
        while d <= end + timedelta(days=40):
            if d.weekday() < 5:
                for ccy in START_LEVELS:
                    shock = rng.gauss(0, 1) * ANNUAL_VOL[ccy] * math.sqrt(dt)
                    level[ccy] *= math.exp(DRIFT[ccy] * dt + shock)
                    self.eur[(d, ccy)] = round_rate(Decimal(repr(level[ccy])), PUBLISHED_RATE_PRECISION)
            d += timedelta(days=1)
        self._avg: dict[tuple[str, str], Decimal] = {}
        self._end: dict[tuple[str, str], Decimal] = {}
        by_month: dict[tuple[str, str], list[tuple[date, Decimal]]] = {}
        for (d, ccy), r in self.eur.items():
            by_month.setdefault((period_of(d), ccy), []).append((d, r))
        for key, vals in by_month.items():
            vals.sort()
            self._avg[key] = round_rate(sum(v for _, v in vals) / len(vals), PUBLISHED_RATE_PRECISION)
            self._end[key] = vals[-1][1]

    # ------------------------------------------------------------------ lookups (EUR triangulation)
    def _eur_spot(self, d: date, ccy: str) -> Decimal:
        if ccy == "EUR":
            return Decimal(1)
        for back in range(MAX_LOOKBACK_DAYS + 1):
            r = self.eur.get((d - timedelta(days=back), ccy))
            if r is not None:
                return r
        raise MissingExchangeRateError(f"no EUR/{ccy} spot within {MAX_LOOKBACK_DAYS} days of {d}")

    def spot(self, d: date, source: str, target: str) -> Decimal:
        if source == target:
            return Decimal(1)
        return cross_rate(self._eur_spot(d, source), self._eur_spot(d, target))

    def month_avg(self, period: str, source: str, target: str) -> Decimal:
        if source == target:
            return Decimal(1)
        s = Decimal(1) if source == "EUR" else self._avg[(period, source)]
        t = Decimal(1) if target == "EUR" else self._avg[(period, target)]
        return cross_rate(s, t)

    def month_end(self, period: str, source: str, target: str) -> Decimal:
        if source == target:
            return Decimal(1)
        s = Decimal(1) if source == "EUR" else self._end[(period, source)]
        t = Decimal(1) if target == "EUR" else self._end[(period, target)]
        return cross_rate(s, t)

    # ------------------------------------------------------------------------ provider publication
    def publication_rows(self) -> list[dict]:
        rows: list[dict] = []
        skip_inr = date(self.start.year + 2, 3, 15)
        while skip_inr.weekday() >= 5:
            skip_inr += timedelta(days=1)
        for (d, ccy), r in sorted(self.eur.items()):
            if d < self.start - timedelta(days=10) or d > self.end:
                continue
            if ccy == "INR" and d == skip_inr:
                continue
            rows.append(self._row(d, ccy, r, "SPOT", at(d, 16, 0)))
        periods = sorted({k[0] for k in self._avg})
        for p in periods:
            y, m = map(int, p.split("-"))
            first = date(y, m, 1)
            if first > self.end or first < date(self.start.year, self.start.month, 1) - timedelta(days=1):
                continue
            last_bd = max(d for (d, c) in self.eur if c == "USD" and period_of(d) == p)
            for ccy in START_LEVELS:
                rows.append(self._row(last_bd, ccy, self._avg[(p, ccy)], "MONTH_AVG", at(last_bd, 17, 30)))
                rows.append(self._row(last_bd, ccy, self._end[(p, ccy)], "MONTH_END", at(last_bd, 17, 30)))
        # Correction scenario: wrong USD spot first, corrected the next morning (value used = corrected).
        corr_day = date(self.start.year + 1, 6, 15)
        while corr_day.weekday() >= 5:
            corr_day += timedelta(days=1)
        good = self.eur[(corr_day, "USD")]
        for row in rows:
            if row["rate_date"] == corr_day and row["source_currency"] == "EUR" and row["target_currency"] == "USD" \
                    and row["rate_type"] == "SPOT":
                row["exchange_rate"] = round_rate(good * Decimal("1.0500"), PUBLISHED_RATE_PRECISION)
        rows.append(self._row(corr_day, "USD", good, "SPOT", at(corr_day + timedelta(days=1), 8, 15)))
        # Invalid publication (zero rate) published after the valid one – must be quarantined.
        bad_day = date(self.start.year + 3, 9, 10)
        while bad_day.weekday() >= 5:
            bad_day += timedelta(days=1)
        rows.append(self._row(bad_day, "GBP", Decimal("0"), "SPOT", at(bad_day, 19, 45)))
        return rows

    @staticmethod
    def _row(d: date, ccy: str, rate: Decimal, rate_type: str, published) -> dict:
        return {
            "rate_date": d, "source_currency": "EUR", "target_currency": ccy, "exchange_rate": rate,
            "rate_type": rate_type, "provider": "HALCYON-FX", "publication_timestamp": published,
        }
