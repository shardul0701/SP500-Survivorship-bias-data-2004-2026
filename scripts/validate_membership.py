#!/usr/bin/env python3
"""Validate native membership YAML and write a Markdown report."""

from __future__ import annotations

import argparse

from refresh_lib import write_validation_report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=("nq100", "sp500"))
    args = parser.parse_args()
    errors, warnings, summary = write_validation_report(args.index)
    print(
        f"{summary['index_name']}: {summary['files']} files, "
        f"{len(errors)} error(s), {len(warnings)} warning(s)"
    )
    for error in errors:
        print(f"ERROR: {error}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
