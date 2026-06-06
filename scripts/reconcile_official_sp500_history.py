#!/usr/bin/env python3
"""Compare parsed official S&P events with existing membership YAML."""

import argparse

from refresh_lib import reconcile_official_history


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=2026)
    parser.add_argument("--threshold", type=float, default=0.90)
    args = parser.parse_args()
    result = reconcile_official_history(
        "sp500",
        args.start_year,
        args.end_year,
        threshold=args.threshold,
    )
    print(result["summary"])
