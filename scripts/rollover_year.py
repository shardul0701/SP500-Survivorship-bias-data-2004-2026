#!/usr/bin/env python3
"""Year-file housekeeping, run before every refresh.

Creates the current year's membership file if it does not exist yet (see
refresh_lib.rollover_year) and clears ``pending`` from changes whose effective
date has arrived (see refresh_lib.expire_elapsed_pending).
"""

from __future__ import annotations

import argparse

from refresh_lib import expire_elapsed_pending, rollover_year


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=("nq100", "sp500"))
    args = parser.parse_args()
    path = rollover_year(args.index)
    print(f"created {path.name}" if path else "current year file already exists")
    cleared = expire_elapsed_pending(args.index)
    print(f"cleared pending on {', '.join(cleared)}" if cleared else "no elapsed pending flags")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
