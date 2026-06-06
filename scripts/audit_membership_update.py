#!/usr/bin/env python3
"""Generate candidate diff and official-source confidence reports."""

from refresh_lib import build_audit_reports


if __name__ == "__main__":
    summary = build_audit_reports()
    print(
        f"Audit complete: {summary['candidates']} candidate(s), "
        f"{summary['manual_review']} manual-review item(s)."
    )
