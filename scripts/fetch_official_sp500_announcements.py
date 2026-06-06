#!/usr/bin/env python3
"""Fetch official S&P 500 announcements when run in the S&P repository."""

import argparse
from datetime import date

from refresh_lib import fetch_official_candidates


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--history-start",
        type=date.fromisoformat,
        help="Paginate the official press archive from this announcement date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--history-end",
        type=date.fromisoformat,
        help="Ignore announcements after this date (YYYY-MM-DD).",
    )
    args = parser.parse_args()
    rows = fetch_official_candidates(
        "sp500",
        history_start=args.history_start,
        history_end=args.history_end,
    )
    print(f"Wrote {len(rows)} S&P 500 candidate change(s).")
