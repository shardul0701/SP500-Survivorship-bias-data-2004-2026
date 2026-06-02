"""
audit_membership.py

Generates a human-readable audit report for the S&P 500 YAML dataset:

  1. Jan 1 member count for every year
  2. Total additions and removals per year
  3. Top 5 largest single-day changes (most tickers added + removed)
  4. Total unique tickers ever in the index across 2004-2026

Saves the report to audit/audit_report.txt and also prints it to stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPTS_DIR = Path(__file__).parent
REPO_ROOT = SCRIPTS_DIR.parent
YAML_DIR = REPO_ROOT / "src" / "sp500_ticker_history"
AUDIT_DIR = REPO_ROOT / "audit"

YEARS = list(range(2004, 2027))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_year(year: int) -> dict:
    path = YAML_DIR / f"sp500-ticker-changes-{year}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def build_report() -> str:
    lines = []
    lines.append("=" * 64)
    lines.append("S&P 500 YAML Dataset — Membership Audit Report")
    lines.append("=" * 64)
    lines.append("")

    # -- Section 1 & 2: Per-year counts ----------------------------------
    lines.append("SECTION 1 & 2: Per-Year Member Count and Change Summary")
    lines.append("-" * 64)
    lines.append(f"{'Year':<6}  {'Jan 1 Count':>11}  {'Adds':>6}  {'Removes':>8}  {'Net':>5}  {'Change Dates':>13}")
    lines.append("-" * 64)

    all_single_day: list[tuple[int, str, int]] = []  # (year, date, count)
    all_tickers: set[str] = set()

    for year in YEARS:
        data = load_year(year)
        if not data:
            lines.append(f"{year:<6}  {'N/A':>11}  {'N/A':>6}  {'N/A':>8}  {'N/A':>5}  {'N/A':>13}")
            continue

        jan1 = data.get("tickers_on_Jan_1", [])
        all_tickers.update(jan1)

        changes = data.get("changes") or {}
        total_adds = 0
        total_removes = 0

        for date_str, entry in changes.items():
            added = entry.get("union", [])
            removed = entry.get("difference", [])
            total_adds += len(added)
            total_removes += len(removed)
            day_total = len(added) + len(removed)
            all_single_day.append((year, date_str, day_total))
            all_tickers.update(added)
            all_tickers.update(removed)

        net = total_adds - total_removes
        lines.append(
            f"{year:<6}  {len(jan1):>11}  {total_adds:>6}  {total_removes:>8}  {net:>+5}  {len(changes):>13}"
        )

    lines.append("")

    # -- Section 3: Top 5 largest single-day change dates -----------------
    lines.append("SECTION 3: Top 5 Largest Single-Day Changes (adds + removes)")
    lines.append("-" * 64)
    top5 = sorted(all_single_day, key=lambda x: x[2], reverse=True)[:5]
    lines.append(f"{'Rank':<6}  {'Year':<6}  {'Date':<12}  {'Tickers Moved':>14}")
    lines.append("-" * 40)
    for rank, (year, date_str, count) in enumerate(top5, 1):
        lines.append(f"{rank:<6}  {year:<6}  {date_str:<12}  {count:>14}")
    lines.append("")

    # -- Section 4: Unique ticker count ----------------------------------
    lines.append("SECTION 4: Total Unique Tickers")
    lines.append("-" * 64)
    lines.append(f"  Total unique tickers ever in S&P 500 (2004–2026): {len(all_tickers)}")
    lines.append("")
    lines.append("  (Note: tickers from 2020-2026 are carried forward from 2019-01-11,")
    lines.append("   the last date in the source CSV. Source: fja05680/sp500 on GitHub.)")
    lines.append("")

    # -- Sorted unique tickers list (brief) --------------------------------
    sorted_tickers = sorted(all_tickers)
    lines.append(f"  First 20 tickers: {', '.join(sorted_tickers[:20])}")
    lines.append(f"  Last  20 tickers: {', '.join(sorted_tickers[-20:])}")
    lines.append("")
    lines.append("=" * 64)

    return "\n".join(lines)


def main() -> None:
    AUDIT_DIR.mkdir(exist_ok=True)
    report = build_report()
    print(report)

    out_path = AUDIT_DIR / "audit_report.txt"
    out_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {out_path}")


if __name__ == "__main__":
    main()
