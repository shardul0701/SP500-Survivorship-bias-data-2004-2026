#!/usr/bin/env python3
"""Fetch and parse official Nasdaq-100 membership announcements."""

from refresh_lib import fetch_official_candidates


if __name__ == "__main__":
    rows = fetch_official_candidates("nq100")
    print(f"Wrote {len(rows)} Nasdaq-100 candidate change(s).")
