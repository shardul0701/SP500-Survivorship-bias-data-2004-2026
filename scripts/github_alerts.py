"""One deduplicated GitHub issue per alert, opened, updated and closed by the workflow.

The refresh workflow used to report problems only as ::warning:: lines in a job
log, and a log nobody opens is not an alert -- every 2026 miss sat in plain
sight that way. An issue is visible on the repository front page, emails
watchers, and stays open until the condition clears.

Rules:
* one open issue per alert key, found by a hidden marker in its body (the
  issue search index lags, so the marker is matched on a direct listing);
* the body is rewritten in place every run (no notification);
* a comment is added only when the condition itself changes (fingerprint), so
  a persisting problem does not spam watchers daily;
* the issue is closed, with a comment, on the first run where it clears;
* every write is read back and compared -- an API call that "succeeds" with
  the wrong content is treated as a failure.

Bodies go to the REST API as JSON, never through a shell argument.
Without GITHUB_TOKEN/GITHUB_REPOSITORY (a local run) alerting is skipped.
"""

from __future__ import annotations

import hashlib
import json
import os

import requests

API = "https://api.github.com"
LABEL_COLOURS = {"live-check": "b60205", "manual-review": "fbca04"}


def fingerprint(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _marker(key: str) -> str:
    return f"<!-- pit-alert:{key} -->"


def _fp_line(fp: str) -> str:
    return f"<!-- pit-alert-fingerprint:{fp} -->"


def _fp_of(body: str) -> str | None:
    tag = "<!-- pit-alert-fingerprint:"
    start = body.find(tag)
    if start < 0:
        return None
    return body[start + len(tag) :].split(" -->", 1)[0].strip()


class GitHub:
    def __init__(self, repo: str, token: str, session=None):
        self.repo = repo
        self.s = session or requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )

    @classmethod
    def from_env(cls) -> "GitHub | None":
        repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
        return cls(repo, token) if repo and token else None

    def _call(self, method: str, path: str, **kwargs):
        resp = self.s.request(method, f"{API}/repos/{self.repo}{path}", timeout=30, **kwargs)
        if resp.status_code >= 400:
            raise RuntimeError(f"GitHub {method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json() if resp.content else {}

    def ensure_label(self, label: str) -> None:
        resp = self.s.get(f"{API}/repos/{self.repo}/labels/{label}", timeout=30)
        if resp.status_code == 404:
            self._call(
                "POST",
                "/labels",
                json={"name": label, "color": LABEL_COLOURS.get(label, "ededed")},
            )

    def open_issue(self, key: str, label: str) -> dict | None:
        marker = _marker(key)
        issues = self._call(
            "GET", "/issues", params={"state": "open", "labels": label, "per_page": 100}
        )
        for issue in issues:
            if "pull_request" not in issue and marker in (issue.get("body") or ""):
                return issue
        return None

    def _verify(self, number: int, field: str, expected: str) -> None:
        got = self._call("GET", f"/issues/{number}").get(field) or ""
        if got.strip() != expected.strip():
            raise RuntimeError(f"issue #{number} {field} did not round-trip intact")

    def _comment(self, number: int, body: str) -> None:
        made = self._call("POST", f"/issues/{number}/comments", json={"body": body})
        got = self._call("GET", f"/issues/comments/{made['id']}").get("body") or ""
        if got.strip() != body.strip():
            raise RuntimeError(f"comment on #{number} did not round-trip intact")


def upsert_alert(gh: GitHub, key: str, label: str, title: str, body: str, condition) -> str:
    """Open, refresh or escalate the alert. Returns a one-line description."""
    fp = fingerprint(condition)
    full = f"{_marker(key)}\n{_fp_line(fp)}\n\n{body}"
    gh.ensure_label(label)
    issue = gh.open_issue(key, label)
    if issue is None:
        made = gh._call("POST", "/issues", json={"title": title, "body": full, "labels": [label]})
        gh._verify(made["number"], "body", full)
        return f"opened #{made['number']}"
    number = issue["number"]
    changed = _fp_of(issue.get("body") or "") != fp
    gh._call("PATCH", f"/issues/{number}", json={"title": title, "body": full})
    gh._verify(number, "body", full)
    if changed:
        gh._comment(number, "The condition changed; the description above is current.\n\n" + body)
        return f"updated #{number} (condition changed, commented)"
    return f"refreshed #{number} (unchanged)"


def resolve_alert(gh: GitHub, key: str, label: str, note: str) -> str:
    issue = gh.open_issue(key, label)
    if issue is None:
        return "no open alert"
    number = issue["number"]
    gh._comment(number, note)
    gh._call("PATCH", f"/issues/{number}", json={"state": "closed", "state_reason": "completed"})
    if gh._call("GET", f"/issues/{number}").get("state") != "closed":
        raise RuntimeError(f"issue #{number} did not close")
    return f"closed #{number}"
