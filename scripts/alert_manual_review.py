#!/usr/bin/env python3
"""Raise a GitHub issue for official releases the crawler found but could not apply.

audit/manual_review_required.csv is rewritten every run and was only ever read
by the PR step -- which runs only when the YAML changed. A release that parsed
to nothing therefore changed nothing, opened no PR, and its review row was
never seen: the Lumentum release sat there from May. This surfaces every
outstanding row as an issue whether or not a PR exists.

A row is outstanding until its source_url is either recorded in the YAML
(the change was entered) or listed in metadata/manual_review_ack.yaml (a human
looked and decided it is not a membership change).
"""

from __future__ import annotations

import argparse
import sys

import yaml

from github_alerts import GitHub, resolve_alert, upsert_alert
from refresh_lib import AUDIT_DIR, METADATA_DIR, profile, read_csv

ACK_FILE = METADATA_DIR / "manual_review_ack.yaml"


def recorded_source_urls(index: str) -> set[str]:
    prof = profile(index)
    urls = set()
    for path in prof["data_dir"].glob(prof["glob"]):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in (data.get("changes") or {}).values():
            for key in ("source_url", "evidence_url"):
                if (entry or {}).get(key):
                    urls.add(str(entry[key]).strip())
    return urls


def acknowledged_urls() -> set[str]:
    if not ACK_FILE.exists():
        return set()
    data = yaml.safe_load(ACK_FILE.read_text(encoding="utf-8")) or {}
    return {str(item["source_url"]).strip() for item in (data.get("acknowledged") or [])}


def outstanding(index: str) -> list[dict]:
    name = profile(index)["index_name"]
    done = recorded_source_urls(index) | acknowledged_urls()
    rows, seen = [], set()
    for row in read_csv(AUDIT_DIR / "manual_review_required.csv"):
        url = (row.get("source_url") or "").strip()
        if row.get("index_name") != name or url in done or url in seen:
            continue
        seen.add(url)
        rows.append(row)
    return rows


def render(index: str, rows: list[dict]) -> tuple[str, str]:
    name = profile(index)["index_name"]
    title = f"[manual-review] {len(rows)} {name} release(s) need a human"
    lines = [
        "The crawler fetched these official releases but could not turn them into a "
        "validated change, so nothing was applied to the YAML.",
        "",
        "| Effective | Added | Removed | Reason | Release |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        reason = (r.get("review_reason") or r.get("parser_notes") or "").replace("|", "/")[:160]
        lines.append(
            f"| {r.get('effective_date') or '?'} | {r.get('added_tickers') or '-'} | "
            f"{r.get('removed_tickers') or '-'} | {reason} | [{(r.get('source_title') or 'link')[:60]}]"
            f"({r.get('source_url')}) |"
        )
    lines += [
        "",
        "**To clear a row:** enter the change in the yearly YAML with this `source_url`, "
        "or, if the release is not a membership change, add it to "
        "`metadata/manual_review_ack.yaml` with a reason. The issue closes itself once "
        "no rows remain.",
    ]
    return title, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=("nq100", "sp500"))
    parser.add_argument("--alert", action="store_true")
    parser.add_argument(
        "--count", action="store_true", help="print only the number of outstanding rows (for the workflow)"
    )
    args = parser.parse_args()
    rows = outstanding(args.index)
    if args.count:
        print(len(rows))
        return 0
    print(f"{len(rows)} outstanding manual-review release(s)")
    for r in rows:
        print(f"  {r.get('effective_date') or '?'} {r.get('source_url')}")
    if rows:
        print(f"::warning::{len(rows)} manual-review release(s) outstanding")
    if not args.alert:
        return 0
    gh = GitHub.from_env()
    if gh is None:
        print("alert skipped: GITHUB_TOKEN/GITHUB_REPOSITORY not set (local run)")
        return 0
    key = f"manual-review:{args.index}"
    if rows:
        title, body = render(args.index, rows)
        condition = sorted(r.get("source_url") or "" for r in rows)
        print("alert:", upsert_alert(gh, key, "manual-review", title, body, condition))
    else:
        print("alert:", resolve_alert(gh, key, "manual-review", "Resolved: no outstanding manual-review releases."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
