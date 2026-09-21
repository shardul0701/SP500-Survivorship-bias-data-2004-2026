#!/usr/bin/env python3
"""Write machine-readable and Markdown dataset freshness reports."""

from __future__ import annotations

import argparse

from refresh_lib import check_freshness


STALE = "stale_or_incomplete"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=("nq100", "sp500"))
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help=(
            "Write the reports and always exit 0. For callers that need the "
            "refreshed metadata regardless of confidence -- the enforcement then "
            "belongs in a later, separate step. See .github/workflows/"
            "refresh_membership.yml."
        ),
    )
    args = parser.parse_args()
    result = check_freshness(args.index)
    print(
        f"{result['index_name']}: latest trusted date "
        f"{result['latest_trusted_date']}; {len(result['warnings'])} warning(s)"
    )
    for warning in result["warnings"]:
        print(f"  - {warning}")

    if result["confidence_level"] != STALE:
        return 0

    # A consumer pinning this dataset cannot tell a current roster from one that
    # simply stopped recording events -- both look like "no changes". Exiting 0
    # here made that silence indistinguishable from success for every automated
    # caller. Say it in the exit code, not only in a JSON field nobody reads.
    print(
        f"::error::{result['index_name']} freshness is {STALE}: "
        + "; ".join(result["warnings"])
    )
    if args.no_fail:
        print("--no-fail set; not failing here. A later step must enforce this.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
