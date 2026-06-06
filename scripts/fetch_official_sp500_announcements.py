#!/usr/bin/env python3
"""Fetch official S&P 500 announcements when run in the S&P repository."""

from refresh_lib import fetch_official_candidates


if __name__ == "__main__":
    rows = fetch_official_candidates("sp500")
    print(f"Wrote {len(rows)} S&P 500 candidate change(s).")
