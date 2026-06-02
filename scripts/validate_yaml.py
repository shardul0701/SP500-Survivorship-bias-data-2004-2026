"""
validate_yaml.py

Validates all sp500-ticker-changes-YYYY.yaml files for:
  1. Correct YAML parse (no syntax errors)
  2. No duplicate tickers within a single change entry's difference or union
  3. Ticker count on Jan 1 is between 450 and 560
  4. Year-to-year continuity: last membership of year Y == tickers_on_Jan_1 of Y+1
  5. No change entries with both empty difference AND empty union
  6. Sorted ticker lists (tickers_on_Jan_1 and per-change lists are alphabetical)

Prints PASS/FAIL with detailed diagnostics. Exits with code 0 on all-pass, 1 on any failure.
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

YEARS = list(range(2004, 2027))
MIN_MEMBERS = 450
MAX_MEMBERS = 560

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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
# Simulate end-of-year membership
# ---------------------------------------------------------------------------
def final_membership(data: dict) -> list[str]:
    """Apply all changes in the year and return the final sorted membership."""
    current = set(data.get("tickers_on_Jan_1", []))
    for entry in sorted((data.get("changes") or {}).keys()):
        e = data["changes"][entry]
        current -= set(e.get("difference", []))
        current |= set(e.get("union", []))
    return sorted(current)


# ---------------------------------------------------------------------------
# Validate a single year
# ---------------------------------------------------------------------------
def validate_year(year: int) -> tuple[dict | None, list[str]]:
    """
    Returns (parsed_data_or_None, list_of_error_strings).
    A non-empty error list means the year failed validation.
    """
    path = YAML_DIR / f"sp500-ticker-changes-{year}.yaml"
    errors = []

    # Check 1: file exists
    if not path.exists():
        errors.append(f"{path.name}: file not found")
        return None, errors

    # Check 2: parses as YAML
    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        errors.append(f"{path.name}: YAML parse error — {exc}")
        return None, errors

    if not data:
        errors.append(f"{path.name}: empty or null YAML content")
        return None, errors

    # Check 3: top-level keys exist
    for key in ("year", "tickers_on_Jan_1"):
        if key not in data:
            errors.append(f"{path.name}: missing required key '{key}'")

    if errors:
        return data, errors

    # Check 4: year field matches filename
    if data["year"] != year:
        errors.append(
            f"{path.name}: 'year' field is {data['year']}, expected {year}"
        )

    # Check 5: Jan 1 count in range
    jan1 = data.get("tickers_on_Jan_1", [])
    n = len(jan1)
    if not (MIN_MEMBERS <= n <= MAX_MEMBERS):
        errors.append(
            f"{path.name}: tickers_on_Jan_1 has {n} members "
            f"(expected {MIN_MEMBERS}–{MAX_MEMBERS})"
        )

    # Check 6: Jan 1 list is sorted and no duplicates
    if jan1 != sorted(set(jan1)):
        if sorted(set(jan1)) != sorted(jan1):
            errors.append(f"{path.name}: tickers_on_Jan_1 contains duplicates")
        else:
            errors.append(f"{path.name}: tickers_on_Jan_1 is not sorted alphabetically")

    # Check 7: validate each change entry
    changes = data.get("changes") or {}
    for date_str, entry in changes.items():
        diff = entry.get("difference", [])
        union = entry.get("union", [])

        # Both empty is not allowed
        if not diff and not union:
            errors.append(
                f"{path.name}: change on '{date_str}' has empty difference AND empty union"
            )

        # Duplicate tickers within the same list
        if len(diff) != len(set(diff)):
            errors.append(
                f"{path.name}: change on '{date_str}' has duplicate tickers in 'difference'"
            )
        if len(union) != len(set(union)):
            errors.append(
                f"{path.name}: change on '{date_str}' has duplicate tickers in 'union'"
            )

        # Sorted order
        if diff and diff != sorted(diff):
            errors.append(
                f"{path.name}: change on '{date_str}' 'difference' list is not sorted"
            )
        if union and union != sorted(union):
            errors.append(
                f"{path.name}: change on '{date_str}' 'union' list is not sorted"
            )

    return data, errors


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------
def main() -> int:
    print("=" * 60)
    print("S&P 500 YAML Validation Report")
    print("=" * 60)

    all_passed = True
    year_data: dict[int, dict] = {}

    # Per-year checks (1-5 from spec, plus sorted-list bonus)
    print("\n[1] Per-file validation:")
    for year in YEARS:
        data, errors = validate_year(year)
        year_data[year] = data
        path_name = f"sp500-ticker-changes-{year}.yaml"
        if errors:
            all_passed = False
            print(f"\n  {Color['red']}FAIL{Color['reset']}  {path_name}")
            for e in errors:
                print(f"         {e}")
        else:
            ok(path_name)

    # Check 4: year-to-year continuity
    print("\n[2] Year-to-year membership continuity:")
    for y in YEARS[:-1]:
        next_y = y + 1
        if year_data.get(y) is None or year_data.get(next_y) is None:
            warn(f"  {y}→{next_y}: skipped (missing data)")
            continue

        end_of_y = final_membership(year_data[y])
        jan1_next = sorted(year_data[next_y].get("tickers_on_Jan_1", []))

        if end_of_y != jan1_next:
            all_passed = False
            missing_from_next = sorted(set(end_of_y) - set(jan1_next))
            extra_in_next = sorted(set(jan1_next) - set(end_of_y))
            fail(
                f"{y}->{next_y}: mismatch! "
                f"missing from {next_y}: {missing_from_next[:5]}{'...' if len(missing_from_next) > 5 else ''}, "
                f"extra in {next_y}: {extra_in_next[:5]}{'...' if len(extra_in_next) > 5 else ''}"
            )
        else:
            ok(f"{y}->{next_y}: {len(jan1_next)} tickers match")

    # Summary
    print("\n" + "=" * 60)
    if all_passed:
        print(f"{Color['green']}ALL CHECKS PASSED{Color['reset']}")
    else:
        print(f"{Color['red']}SOME CHECKS FAILED — see details above{Color['reset']}")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
