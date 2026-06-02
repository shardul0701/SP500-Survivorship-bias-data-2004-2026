"""
convert_from_fja05680.py
------------------------
Convert fja05680 S&P 500 historical CSVs into per-year YAML files.

Primary source:
  source_raw/S&P 500 Historical Components & Changes(01-17-2026).csv
  - Daily rows from 1996-01-02 through 2026-01-14
  - Clean tickers (no -YYYYMM suffixes)

Supplementary (cross-reference only, not used in generation):
  source_raw/sp500_changes_since_2019.csv

Output:
  src/sp500_ticker_history/sp500-ticker-changes-YYYY.yaml
  One file per year, 2004-2026.

Coverage after generation:
  2004-2026-01-14 : real data from updated source
  2026-01-15+     : frozen at 2026-01-14 membership (no changes recorded)
"""

import csv
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).parent.parent
SOURCE_CSV = ROOT / "source_raw" / "S&P 500 Historical Components & Changes(01-17-2026).csv"
OUTPUT_DIR = ROOT / "src" / "sp500_ticker_history"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

START_YEAR = 2004
END_YEAR = 2026
DATA_FREEZE_DATE = "2026-01-14"


def parse_tickers(tickers_str: str) -> set:
    return {t.strip() for t in tickers_str.split(",") if t.strip()}


def load_csv(path: Path) -> list:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row["date"].strip()
            tickers = parse_tickers(row["tickers"])
            if tickers:
                rows.append((date, tickers))
    rows.sort(key=lambda x: x[0])
    return rows


def get_membership_before(rows: list, cutoff: str) -> set:
    result = set()
    for date, tickers in rows:
        if date <= cutoff:
            result = tickers
        else:
            break
    return result


def build_yaml_text(year: int, tickers_jan1: set, changes: OrderedDict,
                    frozen: bool = False) -> str:
    lines = []

    if frozen:
        lines.append(f"# WARNING: No source data exists for {year}.")
        lines.append(f"# Membership carried forward from {DATA_FREEZE_DATE}.")
        lines.append("# Update manually when new source data is available.")
        lines.append("")

    lines.append(f"year: {year}")
    lines.append("")
    lines.append("tickers_on_Jan_1:")
    for t in sorted(tickers_jan1):
        lines.append(f"  - '{t}'")

    if changes:
        lines.append("")
        lines.append("changes:")
        for date_str, (removed, added) in changes.items():
            lines.append("")
            lines.append(f"  '{date_str}':")
            if removed:
                lines.append("    difference:")
                for t in sorted(removed):
                    lines.append(f"      - '{t}'")
            if added:
                lines.append("    union:")
                for t in sorted(added):
                    lines.append(f"      - '{t}'")
    else:
        lines.append("")
        lines.append(f"# No membership changes recorded for {year}.")
        lines.append("changes: {}")

    lines.append("")
    return "\n".join(lines)


def main():
    print(f"Loading: {SOURCE_CSV.name}")
    rows = load_csv(SOURCE_CSV)
    print(f"  {len(rows)} rows  ({rows[0][0]} -> {rows[-1][0]})")

    for year in range(START_YEAR, END_YEAR + 1):
        jan1_cutoff = f"{year - 1}-12-31"
        year_start = f"{year}-01-01"
        year_end = f"{year}-12-31"

        tickers_jan1 = get_membership_before(rows, jan1_cutoff)
        if not tickers_jan1:
            print(f"  {year}: No pre-year data found, skipping.")
            continue

        changes: OrderedDict = OrderedDict()
        prev = tickers_jan1

        for date, tickers in rows:
            if date < year_start:
                continue
            if date > year_end:
                break
            removed = prev - tickers
            added = tickers - prev
            if removed or added:
                changes[date] = (removed, added)
            prev = tickers

        # A year is frozen if its entire range is past the data freeze date
        frozen = (year_start > DATA_FREEZE_DATE)

        yaml_text = build_yaml_text(year, tickers_jan1, changes, frozen=frozen)
        out_path = OUTPUT_DIR / f"sp500-ticker-changes-{year}.yaml"
        out_path.write_text(yaml_text, encoding="utf-8")

        n_adds = sum(len(u) for _, (_, u) in changes.items())
        n_rem = sum(len(d) for _, (d, _) in changes.items())
        tag = " [FROZEN]" if frozen else ""
        print(f"  {year}: {len(tickers_jan1):>3} members | "
              f"{len(changes):>2} change dates | +{n_adds} -{n_rem}{tag}")

    print(f"\nDone -> {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
