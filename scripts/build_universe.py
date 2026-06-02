"""
build_universe.py

Provides point-in-time S&P 500 universe lookup from the YAML files.

Public API:
    get_universe_as_of(date_str: str) -> list[str]
    get_all_historical_tickers() -> set[str]

Usage as a script:
    python scripts/build_universe.py 2015-06-01
    python scripts/build_universe.py --all
"""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent
YAML_DIR = REPO_ROOT / "src" / "sp500_ticker_history"

YEARS = range(2004, 2027)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
@lru_cache(maxsize=None)
def _load_year(year: int) -> dict:
    """Load and cache a single year's YAML file. Returns {} if file missing."""
    path = YAML_DIR / f"sp500-ticker-changes-{year}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _apply_changes_up_to(
    base_tickers: list[str],
    changes: dict,
    up_to_date: str,
) -> list[str]:
    """
    Starting from base_tickers, apply all change entries whose date <=
    up_to_date and return the resulting sorted ticker list.
    """
    current = set(base_tickers)
    for date_str in sorted(changes.keys()):
        if date_str > up_to_date:
            break
        entry = changes[date_str]
        current -= set(entry.get("difference", []))
        current |= set(entry.get("union", []))
    return sorted(current)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def get_universe_as_of(date_str: str) -> list[str]:
    """
    Return sorted list of S&P 500 tickers as of the given date (YYYY-MM-DD).

    Works by:
      1. Loading the YAML for the year matching date_str.
      2. Starting with tickers_on_Jan_1.
      3. Applying all changes whose date <= date_str.

    Raises ValueError for dates outside 2004-01-01 to 2026-12-31.
    Returns an empty list if no YAML data is available for the year.
    """
    if not date_str or len(date_str) < 10:
        raise ValueError(f"date_str must be YYYY-MM-DD format, got: {date_str!r}")

    year = int(date_str[:4])
    if year < 2004 or year > 2026:
        raise ValueError(
            f"date {date_str!r} is outside the supported range 2004-01-01 to 2026-12-31"
        )

    data = _load_year(year)
    if not data:
        return []

    base = list(data.get("tickers_on_Jan_1", []))
    changes = data.get("changes") or {}
    return _apply_changes_up_to(base, changes, date_str)


def get_all_historical_tickers() -> set[str]:
    """
    Return the set of all tickers ever in the S&P 500 between 2004 and 2026.

    Scans all YAML files and collects every ticker that appears in
    tickers_on_Jan_1 or in any change entry (difference or union).
    """
    all_tickers: set[str] = set()

    for year in YEARS:
        data = _load_year(year)
        if not data:
            continue
        all_tickers.update(data.get("tickers_on_Jan_1", []))
        for entry in (data.get("changes") or {}).values():
            all_tickers.update(entry.get("difference", []))
            all_tickers.update(entry.get("union", []))

    return all_tickers


# ---------------------------------------------------------------------------
# CLI convenience
# ---------------------------------------------------------------------------
def main() -> None:
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python scripts/build_universe.py YYYY-MM-DD")
        print("  python scripts/build_universe.py --all")
        sys.exit(1)

    if args[0] == "--all":
        tickers = sorted(get_all_historical_tickers())
        print(f"All historical tickers (2004-2026): {len(tickers)} unique")
        print(", ".join(tickers[:20]) + " ...")
    else:
        date_str = args[0]
        try:
            tickers = get_universe_as_of(date_str)
            print(f"S&P 500 as of {date_str}: {len(tickers)} tickers")
            print(", ".join(tickers[:20]) + (" ..." if len(tickers) > 20 else ""))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
