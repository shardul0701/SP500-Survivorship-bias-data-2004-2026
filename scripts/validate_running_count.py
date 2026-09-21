"""
validate_running_count.py

Intra-year validation of the running membership count.

`validate_yaml.py` checks the roster only at year boundaries: that
`final_membership(Y) == tickers_on_Jan_1(Y+1)`, and that each Jan-1 count sits in a
450..560 band. Neither sees an unbalanced change *inside* a year, for two concrete reasons:

  * `refresh_lib.py:1079` creates a new year's roster as
    `"tickers_on_Jan_1": sorted(final_membership(previous))` — derived from the walk. Once
    the fault propagates, both sides of the continuity comparison move together and every
    boundary agrees, in `validate_yaml.py:189` and in `refresh_lib.py:1218` alike.
  * `validate_yaml.py:189` iterates `YEARS[:-1]`, so the year currently being edited — the
    one new changes land in — has no successor to be compared against at all.

So an add recorded without its corresponding drop (or vice versa) shifts the running count
and nothing fails. This script closes that gap.

What it asserts, and why each tolerance is the number it is (all measured against the
committed 2004..2026 data — see MEASURED below):

  [1] Change-entry integrity
      A `difference` entry must name a current member; a `union` entry must not; a ticker
      may not appear in both on one date; a change date must live in its own year file and
      the keys must ascend. MEASURED: 0 violations, so these are hard invariants.

  [2] Per-event delta bound  (|delta| <= MAX_EVENT_DELTA)
      Catches gross corruption (a truncated or duplicated list), not a single missing
      counterpart. MEASURED: deltas span -2..+3, so the bound is loose by design.

  [3] Prevailing-level baseline  (golden master)
      The sequence of levels the roster genuinely occupies is derived here and compared to
      `metadata/membership_count_baseline.json`. A *new* persistent level fails and names
      the date. This is the check that catches a permanently unbalanced change.
      MEASURED: 17 levels / 16 steps, 494 -> 503.

  [4] Deviation episodes close  (<= MAX_DEVIATION_DAYS)
      The count may legitimately sit off its prevailing level between an announcement and
      its counterpart. Every such episode in history closes. MEASURED: 70 episodes, median
      2 days, max 36 (2015-12-14 -> 2016-01-19, spanning the multi-share-class step;
      outside 2015-12..2016-06 the max is 7). An episode still open at HEAD is reported as
      a WARN naming the unbalanced dates, since a fresh edit cannot yet be distinguished
      from a genuine new level.

  [5] Offset bound  (|count - prevailing| <= MAX_OFFSET)
      MEASURED: offsets span -2..+2.

Why a committed baseline rather than an absolute band: the running count is NOT pinned at
500. It ranges 494..507 across the committed data and sits at 497 for 138 of 505 events,
so an absolute assertion would fail on most of the history. Nor can the rule be "no level
may ever change": 16 steps are legitimate — the early years drift up as the dataset fills
in, and 2015-09/2016-01 (+3 then +2) is the multi-share-class era. The baseline records
those as known-and-accepted and makes any *new* step a reviewable one-line diff.

Usage:
    python scripts/validate_running_count.py
    python scripts/validate_running_count.py --strict           # open deviation -> FAIL
    python scripts/validate_running_count.py --update-baseline  # accept a new level

Exits 0 on all-pass, 1 on any failure.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent
YAML_DIR = REPO_ROOT / "src" / "sp500_ticker_history"
BASELINE_PATH = REPO_ROOT / "metadata" / "membership_count_baseline.json"

YEARS = list(range(2004, 2027))

# A run must hold this long to count as a level rather than a deviation. The observed
# duration distribution has a natural break here: episodes close within 36 days, while
# genuine levels hold 34..466 days.
PERSIST_DAYS = 31

# Tolerances. Each is loose relative to the measured extreme so that plausible future data
# does not fail, while gross corruption still does. Measured extremes in the docstring.
MAX_EVENT_DELTA = 6      # observed -2..+3
MAX_DEVIATION_DAYS = 40  # observed max 36
MAX_OFFSET = 5           # observed -2..+2

Color = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "reset": "\033[0m",
}


def ok(msg: str) -> None:
    print(f"  {Color['green']}PASS{Color['reset']}  {msg}")


def fail(msg: str) -> None:
    print(f"  {Color['red']}FAIL{Color['reset']}  {msg}")


def warn(msg: str) -> None:
    print(f"  {Color['yellow']}WARN{Color['reset']}  {msg}")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Event:
    """One point in the running-count series: a Jan-1 mark or a dated change."""

    date: dt.date
    count: int
    delta: int
    year: int
    is_jan1: bool
    dropped: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)


@dataclass
class Episode:
    """A stretch where the running count sits off its prevailing level."""

    start: dt.date
    end: dt.date
    days: int
    peak_offset: int
    events: list[Event]
    is_open: bool = False


def _as_date(key: object) -> dt.date:
    """Change keys are ISO date strings, but PyYAML may already have parsed them."""
    if isinstance(key, dt.datetime):
        return key.date()
    if isinstance(key, dt.date):
        return key
    return dt.date.fromisoformat(str(key)[:10])


def load_years(yaml_dir: Path = YAML_DIR, years: list[int] | None = None) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for year in years if years is not None else YEARS:
        path = yaml_dir / f"sp500-ticker-changes-{year}.yaml"
        with open(path, encoding="utf-8") as fh:
            out[year] = yaml.safe_load(fh) or {}
    return out


def build_series(year_data: dict[int, dict]) -> list[Event]:
    """Walk every Jan-1 roster and change in date order, recording the running count.

    Mirrors `validate_yaml.final_membership`: `difference` is removed, then `union` added.
    """
    series: list[Event] = []
    prev_count: int | None = None
    for year in sorted(year_data):
        data = year_data[year] or {}
        current = set(data.get("tickers_on_Jan_1") or [])
        jan1 = dt.date(year, 1, 1)
        series.append(
            Event(
                date=jan1,
                count=len(current),
                delta=0 if prev_count is None else len(current) - prev_count,
                year=year,
                is_jan1=True,
            )
        )
        prev_count = len(current)
        changes = data.get("changes") or {}
        for key in sorted(changes, key=lambda k: _as_date(k)):
            entry = changes[key] or {}
            dropped = list(entry.get("difference") or [])
            added = list(entry.get("union") or [])
            current -= set(dropped)
            current |= set(added)
            series.append(
                Event(
                    date=_as_date(key),
                    count=len(current),
                    delta=len(current) - prev_count,
                    year=year,
                    is_jan1=False,
                    dropped=dropped,
                    added=added,
                )
            )
            prev_count = len(current)
    return series


# ---------------------------------------------------------------------------
# [1] Change-entry integrity
# ---------------------------------------------------------------------------
def check_entry_integrity(year_data: dict[int, dict]) -> list[str]:
    """Errors that cancel out in the count and so hide from every count-based check."""
    errors: list[str] = []
    for year in sorted(year_data):
        data = year_data[year] or {}
        current = set(data.get("tickers_on_Jan_1") or [])
        changes = data.get("changes") or {}

        keys = [_as_date(k) for k in changes]
        if keys != sorted(keys):
            errors.append(f"{year}: change keys are not in ascending date order")

        for key in sorted(changes, key=lambda k: _as_date(k)):
            date = _as_date(key)
            entry = changes[key] or {}
            dropped = list(entry.get("difference") or [])
            added = list(entry.get("union") or [])

            if date.year != year:
                errors.append(f"{date}: change recorded in the {year} file")

            both = sorted(set(dropped) & set(added))
            if both:
                errors.append(f"{date}: ticker(s) in both difference and union: {both}")

            phantom = sorted(t for t in dropped if t not in current)
            if phantom:
                errors.append(f"{date}: difference drops non-member(s): {phantom}")

            dupe = sorted(t for t in added if t in current)
            if dupe:
                errors.append(f"{date}: union adds existing member(s): {dupe}")

            current -= set(dropped)
            current |= set(added)
    return errors


# ---------------------------------------------------------------------------
# [3] Prevailing level
# ---------------------------------------------------------------------------
def derive_prevailing(series: list[Event], persist_days: int = PERSIST_DAYS) -> list[tuple[dt.date, int]]:
    """The levels the roster genuinely occupies.

    Collapse the series into runs of equal count, measuring each run as the time until the
    count actually changed (not the span of events at that count), keep runs that held at
    least `persist_days`, then drop consecutive duplicates — a count that deviates and
    returns is one level, not three.
    """
    if not series:
        return []

    runs: list[tuple[dt.date, int, int]] = []  # (start, count, days)
    start, level = series[0].date, series[0].count
    for ev in series[1:]:
        if ev.count != level:
            runs.append((start, level, (ev.date - start).days))
            start, level = ev.date, ev.count
    runs.append((start, level, (series[-1].date - start).days))

    levels: list[tuple[dt.date, int]] = []
    for run_start, count, days in runs:
        if days >= persist_days and (not levels or levels[-1][1] != count):
            levels.append((run_start, count))
    return levels


def prevailing_at(levels: list[tuple[dt.date, int]], date: dt.date) -> int | None:
    """The prevailing level on `date`; the first level also covers everything before it."""
    if not levels:
        return None
    level = levels[0][1]
    for eff, count in levels:
        if eff <= date:
            level = count
        else:
            break
    return level


# ---------------------------------------------------------------------------
# [4] Deviation episodes
# ---------------------------------------------------------------------------
def deviation_episodes(series: list[Event], levels: list[tuple[dt.date, int]]) -> list[Episode]:
    episodes: list[Episode] = []
    open_events: list[Event] = []
    start: dt.date | None = None

    for ev in series:
        base = prevailing_at(levels, ev.date)
        offset = 0 if base is None else ev.count - base
        if offset != 0:
            if start is None:
                start = ev.date
                open_events = []
            open_events.append(ev)
        elif start is not None:
            episodes.append(
                Episode(
                    start=start,
                    end=ev.date,
                    days=(ev.date - start).days,
                    peak_offset=max((e.count - prevailing_at(levels, e.date) for e in open_events), key=abs),
                    events=open_events,
                )
            )
            start, open_events = None, []

    if start is not None:
        episodes.append(
            Episode(
                start=start,
                end=series[-1].date,
                days=(series[-1].date - start).days,
                peak_offset=max((e.count - prevailing_at(levels, e.date) for e in open_events), key=abs),
                events=open_events,
                is_open=True,
            )
        )
    return episodes


# ---------------------------------------------------------------------------
# Baseline I/O
# ---------------------------------------------------------------------------
def load_baseline(path: Path = BASELINE_PATH) -> list[tuple[dt.date, int]] | None:
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return [(dt.date.fromisoformat(lv["from"]), int(lv["count"])) for lv in doc.get("levels", [])]


def write_baseline(levels: list[tuple[dt.date, int]], path: Path = BASELINE_PATH) -> None:
    prev: int | None = None
    out = []
    for eff, count in levels:
        item: dict[str, object] = {"from": eff.isoformat(), "count": count}
        if prev is not None:
            item["step"] = count - prev
        out.append(item)
        prev = count
    doc = {
        "_comment": (
            "Accepted prevailing membership-count levels, used as a golden master by "
            "scripts/validate_running_count.py. A new level means a change was recorded "
            "without its counterpart, OR the index genuinely re-sized; confirm which, then "
            "regenerate with --update-baseline so the diff is reviewable."
        ),
        "persist_days": PERSIST_DAYS,
        "generated_by": "scripts/validate_running_count.py --update-baseline",
        "levels": out,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2] if __doc__ else None)
    ap.add_argument("--update-baseline", action="store_true",
                    help="rewrite the accepted-levels baseline from the current data")
    ap.add_argument("--strict", action="store_true",
                    help="treat a still-open deviation episode as a failure")
    args = ap.parse_args(argv)

    print("=" * 68)
    print("S&P 500 Running-Count Validation Report")
    print("=" * 68)

    year_data = load_years(YAML_DIR)
    series = build_series(year_data)
    levels = derive_prevailing(series)
    all_passed = True

    print(f"\n[0] Series: {len(series)} events over {len(year_data)} year files, "
          f"{series[0].date} -> {series[-1].date}, count {series[0].count} -> {series[-1].count}")

    # --- [1] entry integrity ---
    print("\n[1] Change-entry integrity:")
    errors = check_entry_integrity(year_data)
    if errors:
        all_passed = False
        for e in errors[:40]:
            fail(e)
        if len(errors) > 40:
            fail(f"... and {len(errors) - 40} more")
    else:
        ok(f"{sum(1 for e in series if not e.is_jan1)} change entries: no phantom drops, "
           "no duplicate adds, no both-direction tickers, dates in order and in-year")

    # --- [2] per-event delta ---
    print(f"\n[2] Per-event delta within +/-{MAX_EVENT_DELTA}:")
    big = [e for e in series if not e.is_jan1 and abs(e.delta) > MAX_EVENT_DELTA]
    if big:
        all_passed = False
        for e in big:
            fail(f"{e.date}: count moved {e.delta:+d} in one entry "
                 f"(-{len(e.dropped)} / +{len(e.added)}) -> {e.count}")
    else:
        worst = max((e for e in series if not e.is_jan1), key=lambda e: abs(e.delta), default=None)
        ok(f"largest single-entry move {worst.delta:+d} on {worst.date}" if worst else "no change entries")

    # --- [3] prevailing-level baseline ---
    print("\n[3] Prevailing-level baseline:")
    if args.update_baseline:
        write_baseline(levels, BASELINE_PATH)
        print(f"  wrote {BASELINE_PATH.relative_to(REPO_ROOT)} with {len(levels)} levels:")
        prev = None
        for eff, count in levels:
            print(f"         {eff}  {count}" + ("" if prev is None else f"  ({count - prev:+d})"))
            prev = count
    else:
        baseline = load_baseline(BASELINE_PATH)
        if baseline is None:
            all_passed = False
            fail(f"no baseline at {BASELINE_PATH.relative_to(REPO_ROOT)} — "
                 "generate it with --update-baseline and commit it")
        elif baseline != levels:
            all_passed = False
            extra = [lv for lv in levels if lv not in baseline]
            missing = [lv for lv in baseline if lv not in levels]
            fail(f"derived {len(levels)} levels, baseline has {len(baseline)}")
            for eff, count in extra:
                ev = next((e for e in series if e.date == eff), None)
                detail = (f" (entry -{len(ev.dropped)} / +{len(ev.added)})" if ev and not ev.is_jan1 else "")
                fail(f"  NEW level not in baseline: {eff} -> {count}{detail}")
            for eff, count in missing:
                fail(f"  baseline level no longer derived: {eff} -> {count}")
            print("         A new level means a change was recorded without its counterpart,")
            print("         or the index genuinely re-sized. Confirm which, then re-run with")
            print("         --update-baseline to accept it as a reviewable diff.")
        else:
            ok(f"{len(levels)} accepted levels match "
               f"({levels[0][1]} on {levels[0][0]} -> {levels[-1][1]} on {levels[-1][0]})")

    # --- [4] deviation episodes ---
    print(f"\n[4] Deviation episodes close within {MAX_DEVIATION_DAYS} days:")
    episodes = deviation_episodes(series, levels)
    closed = [ep for ep in episodes if not ep.is_open]
    stale = [ep for ep in closed if ep.days > MAX_DEVIATION_DAYS]
    if stale:
        all_passed = False
        for ep in stale:
            fail(f"{ep.start} -> {ep.end}: off-level for {ep.days} days "
                 f"(peak {ep.peak_offset:+d})")
    else:
        longest = max((ep.days for ep in closed), default=0)
        ok(f"{len(closed)} closed episodes, longest {longest} days")

    for ep in (ep for ep in episodes if ep.is_open):
        unbalanced = [e for e in ep.events if e.delta != 0 and not e.is_jan1]
        msg = (f"deviation still OPEN since {ep.start} ({ep.days} days, offset "
               f"{ep.peak_offset:+d}) — the count has not returned to its prevailing level")
        if args.strict:
            all_passed = False
            fail(msg)
        else:
            warn(msg)
        for e in unbalanced[:10]:
            print(f"         {e.date}: {e.delta:+d}  -{len(e.dropped)} {e.dropped[:4]} "
                  f"/ +{len(e.added)} {e.added[:4]}")
        print("         If one of these is missing its counterpart, fix the entry. If the")
        print("         index genuinely re-sized, accept it with --update-baseline.")

    # --- [5] offset bound ---
    print(f"\n[5] Offset from prevailing level within +/-{MAX_OFFSET}:")
    wide = [(e, e.count - prevailing_at(levels, e.date)) for e in series]
    wide = [(e, off) for e, off in wide if off is not None and abs(off) > MAX_OFFSET]
    if wide:
        all_passed = False
        for e, off in wide[:20]:
            fail(f"{e.date}: count {e.count} is {off:+d} from prevailing "
                 f"{prevailing_at(levels, e.date)}")
    else:
        offs = [e.count - prevailing_at(levels, e.date) for e in series]
        on_level = offs.count(0)
        ok(f"offsets span {min(offs):+d}..{max(offs):+d}; "
           f"{on_level}/{len(offs)} events ({on_level / len(offs):.1%}) exactly on-level")

    print("\n" + "=" * 68)
    if all_passed:
        print(f"{Color['green']}ALL CHECKS PASSED{Color['reset']}")
    else:
        print(f"{Color['red']}SOME CHECKS FAILED — see details above{Color['reset']}")
    print("=" * 68)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
