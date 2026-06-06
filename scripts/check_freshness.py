#!/usr/bin/env python3
"""Write machine-readable and Markdown dataset freshness reports."""

from __future__ import annotations

import argparse

from refresh_lib import check_freshness


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=("nq100", "sp500"))
    args = parser.parse_args()
    result = check_freshness(args.index)
    print(
        f"{result['index_name']}: latest trusted date "
        f"{result['latest_trusted_date']}; {len(result['warnings'])} warning(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
