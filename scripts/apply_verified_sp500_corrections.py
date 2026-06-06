#!/usr/bin/env python3
"""Apply the verified official S&P 500 corrections found by reconciliation."""

import argparse
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from refresh_lib import AUDIT_DIR, iso_now, read_csv, yaml_path, yaml_rt


# These dates are backed by high-confidence official S&P table rows. They fix
# collapsed multi-day events, one misplaced event, one wrong month, and 2026.
VERIFIED_DATES = {
    "2020-10-09",
    "2020-10-12",
    "2021-06-03",
    "2021-06-04",
    "2022-02-02",
    "2022-02-03",
    "2022-12-15",
    "2022-12-19",
    "2023-01-04",
    "2023-01-05",
    "2023-06-19",
    "2023-10-02",
    "2023-10-03",
    "2023-10-18",
    "2023-12-18",
    "2024-04-01",
    "2024-04-02",
    "2024-04-03",
    "2025-03-24",
    "2026-02-09",
    "2026-03-23",
    "2026-04-09",
    "2026-05-07",
    "2026-06-01",
    "2026-06-02",
    "2026-06-22",
}

SUPERSEDED_DATES = {
    "2023-06-20": ("2023-06-19", "official effective date is 2023-06-19"),
    "2025-04-24": ("2025-03-24", "official effective date is 2025-03-24"),
}


def official_events() -> dict[str, dict]:
    path = AUDIT_DIR / "sp500_official_candidates.csv"
    if not path.exists():
        raise FileNotFoundError(
            "Run fetch_official_sp500_announcements.py with historical bounds first."
        )
    events: dict[str, dict] = {}
    for row in read_csv(path):
        effective_date = row.get("effective_date", "")
        if effective_date not in VERIFIED_DATES:
            continue
        if row.get("manual_review_required", "").lower() == "true":
            continue
        if float(row.get("confidence_score", 0)) < 0.90:
            continue
        event = events.setdefault(
            effective_date,
            {"added": set(), "removed": set(), "sources": {}},
        )
        event["added"].update(filter(None, row.get("added_tickers", "").split(";")))
        event["removed"].update(filter(None, row.get("removed_tickers", "").split(";")))
        event["sources"][row["source_url"]] = {
            "source_url": row["source_url"],
            "source_title": row["source_title"],
            "announcement_date": row["announcement_date"],
            "confidence_score": float(row["confidence_score"]),
        }

    missing = sorted(VERIFIED_DATES - set(events))
    if missing:
        raise RuntimeError(f"Official candidates missing verified dates: {missing}")
    return events


def entry_for(effective_date: str, event: dict) -> dict:
    entry = {}
    if event["removed"]:
        entry["difference"] = sorted(event["removed"])
    if event["added"]:
        entry["union"] = sorted(event["added"])
    sources = list(event["sources"].values())
    if len(sources) != 1:
        raise RuntimeError(
            f"{effective_date} expected one official source, found {len(sources)}"
        )
    entry.update(sources[0])
    if date.fromisoformat(effective_date) > date.today():
        entry["pending"] = True
    return entry


def apply_verified(apply: bool) -> list[str]:
    events = official_events()
    parser = yaml_rt()
    touched: dict[int, object] = {}
    actions = []

    for stale_date, (replacement_date, reason) in SUPERSEDED_DATES.items():
        year = int(stale_date[:4])
        data = touched.get(year)
        if data is None:
            with yaml_path("sp500", year).open(encoding="utf-8") as handle:
                data = parser.load(handle)
            touched[year] = data
        if stale_date in (data.get("changes") or {}):
            del data["changes"][stale_date]
            actions.append(f"remove {stale_date}: {reason}")
        elif replacement_date in (data.get("changes") or {}):
            actions.append(f"already removed {stale_date}: {reason}")
        else:
            raise RuntimeError(
                f"Neither superseded nor replacement YAML event exists: "
                f"{stale_date}, {replacement_date}"
            )

    for effective_date in sorted(VERIFIED_DATES):
        year = int(effective_date[:4])
        data = touched.get(year)
        if data is None:
            with yaml_path("sp500", year).open(encoding="utf-8") as handle:
                data = parser.load(handle)
            touched[year] = data
        data.setdefault("changes", {})[effective_date] = entry_for(
            effective_date, events[effective_date]
        )
        actions.append(
            f"set {effective_date}: "
            f"+{','.join(sorted(events[effective_date]['added'])) or '-'} "
            f"-{','.join(sorted(events[effective_date]['removed'])) or '-'}"
        )

    if apply:
        for year, data in touched.items():
            data["changes"] = dict(
                sorted(data["changes"].items(), key=lambda item: str(item[0]))
            )
            with yaml_path("sp500", year).open("w", encoding="utf-8") as handle:
                parser.dump(data, handle)

    report = [
        "# Verified S&P 500 Corrections",
        "",
        f"Generated: {iso_now()}",
        f"Applied: {str(apply).lower()}",
        "",
        "Ambiguous ticker-transition cases were intentionally excluded.",
        "",
    ]
    report.extend(f"- {action}" for action in actions)
    (AUDIT_DIR / "verified_sp500_corrections.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    return actions


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    actions = apply_verified(args.apply)
    print(f"{'Applied' if args.apply else 'Planned'} {len(actions)} correction actions.")
