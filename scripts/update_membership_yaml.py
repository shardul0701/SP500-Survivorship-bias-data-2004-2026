#!/usr/bin/env python3
"""Safely apply high-confidence official candidates to native yearly YAML."""

from __future__ import annotations

import argparse

from refresh_lib import apply_candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=("nq100", "sp500"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--correction-mode", action="store_true")
    parser.add_argument("--confidence-threshold", type=float, default=0.90)
    args = parser.parse_args()

    actions = apply_candidates(
        args.index,
        apply=args.apply,
        correction_mode=args.correction_mode,
        threshold=args.confidence_threshold,
    )
    for action in actions:
        print(
            f"{action['effective_date']}: {action['status']} "
            f"+{action['added']} -{action['removed']} ({action['reason']})"
        )
    print(f"{'Applied' if args.apply else 'Dry-run planned'} {len(actions)} candidate(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
