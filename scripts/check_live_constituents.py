#!/usr/bin/env python3
"""Diff the PIT YAML against the official current member list (see live_check.py).

    check_live_constituents.py --index nq100 [--alert]   # fetch, diff, write state
    check_live_constituents.py --index nq100 --gate      # exit 1 if the last check needs attention

The check itself always exits 0 so the workflow can still commit the state
file and refresh the alert; --gate, run as the workflow's last step, reads the
state just written and turns the run red when a human is needed.
"""

from __future__ import annotations

import argparse

from github_alerts import GitHub, resolve_alert, upsert_alert
from live_check import PROFILES, load_state, needs_attention, render_issue, run_check


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=sorted(PROFILES))
    parser.add_argument("--alert", action="store_true", help="open/update/close the GitHub issue")
    parser.add_argument("--gate", action="store_true", help="only evaluate the saved state")
    args = parser.parse_args()

    if args.gate:
        state = load_state()
        if state is None:
            print("::error::live constituent check has never run")
            return 1
        if needs_attention(state):
            print(f"::error::live constituent check status is {state['status']} -- see the live-check issue")
            return 1
        print(f"live constituent check: {state['status']} ({state['checked_at']})")
        return 0

    state = run_check(args.index)
    for src in state["sources"]:
        if src["reachable"]:
            print(
                f"{src['role']:8s} {src['name']}: as of {src['as_of']}, {src['count']} members; "
                f"missing from YAML {src['missing_from_pit'] or '-'}; extra in YAML {src['extra_in_pit'] or '-'}"
            )
        else:
            print(f"{src['role']:8s} {src['name']}: UNREACHABLE {src['error']}")
    print(f"status: {state['status']} (YAML members today: {state['pit_count_today']})")
    if state["status"] != "pass":
        print(f"::warning::live constituent check: {state['status']}")

    if args.alert:
        gh = GitHub.from_env()
        if gh is None:
            print("alert skipped: GITHUB_TOKEN/GITHUB_REPOSITORY not set (local run)")
        elif needs_attention(state):
            off = state["sources"][0]
            title, body = render_issue(state)
            condition = [state["status"], off["missing_from_pit"], off["extra_in_pit"], bool(off["error"])]
            print("alert:", upsert_alert(gh, f"live-check:{args.index}", "live-check", title, body, condition))
        elif state["status"] == "pass":
            note = (
                f"Resolved: the {state['index_name']} YAML matches the official list "
                f"({state['sources'][0]['count']} members, as of {state['sources'][0]['as_of']})."
            )
            print("alert:", resolve_alert(gh, f"live-check:{args.index}", "live-check", note))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
