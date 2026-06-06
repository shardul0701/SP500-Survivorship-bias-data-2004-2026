#!/usr/bin/env python3
"""Backfill one-source official provenance for exact reconciled YAML events."""

import argparse
import json

from refresh_lib import AUDIT_DIR, iso_now, yaml_path, yaml_rt


def backfill(apply: bool) -> dict:
    reconciliation_path = AUDIT_DIR / "sp500_2019_2026_reconciliation.json"
    if not reconciliation_path.exists():
        raise FileNotFoundError(
            "Run reconcile_official_sp500_history.py before metadata backfill."
        )
    reconciliation = json.loads(reconciliation_path.read_text(encoding="utf-8"))
    parser = yaml_rt()
    touched = {}
    added = []
    already_present = []
    multi_source = []

    for event in reconciliation["exact_matches"]:
        effective_date = event["effective_date"]
        sources = event["sources"]
        if len(sources) != 1:
            multi_source.append(effective_date)
            continue
        year = int(effective_date[:4])
        data = touched.get(year)
        if data is None:
            with yaml_path("sp500", year).open(encoding="utf-8") as handle:
                data = parser.load(handle)
            touched[year] = data
        entry = data["changes"][effective_date]
        if sorted(entry.get("union") or []) != event["added"]:
            raise RuntimeError(f"Addition mismatch after reconciliation: {effective_date}")
        if sorted(entry.get("difference") or []) != event["removed"]:
            raise RuntimeError(f"Removal mismatch after reconciliation: {effective_date}")
        if entry.get("source_url"):
            already_present.append(effective_date)
            continue
        source = sources[0]
        entry["source_url"] = source["source_url"]
        entry["source_title"] = source["source_title"]
        entry["announcement_date"] = source["announcement_date"]
        entry["confidence_score"] = source["confidence_score"]
        added.append(effective_date)

    if apply:
        for year, data in touched.items():
            with yaml_path("sp500", year).open("w", encoding="utf-8") as handle:
                parser.dump(data, handle)

    result = {
        "generated_at": iso_now(),
        "applied": apply,
        "metadata_added": added,
        "already_present": already_present,
        "skipped_multi_source": multi_source,
    }
    (AUDIT_DIR / "sp500_source_metadata_backfill.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = backfill(args.apply)
    print(
        f"{'Applied' if args.apply else 'Planned'} metadata for "
        f"{len(result['metadata_added'])} event(s); "
        f"skipped {len(result['skipped_multi_source'])} multi-source date(s)."
    )
