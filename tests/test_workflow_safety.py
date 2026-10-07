"""Pin the fail-closed ordering of the automated membership refresh."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_refresh_cannot_auto_merge_before_all_release_gates():
    workflow = (ROOT / ".github" / "workflows" / "refresh_membership.yml").read_text(
        encoding="utf-8"
    )
    opened = workflow.index("- name: Open review pull request")
    live_gate = workflow.index("- name: Gate on the live constituent check")
    alert_gate = workflow.index("- name: Fail if an alert could not be raised")
    freshness_gate = workflow.index("- name: Fail the run if the dataset is stale or incomplete")
    merge = workflow.index("- name: Auto-merge the validated membership PR")
    assert opened < live_gate < alert_gate < freshness_gate < merge
    assert "gh pr merge" not in workflow[opened:live_gate]


def test_validation_uses_branch_push_not_unstartable_bot_pr_event():
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
    triggers = workflow.split("jobs:", 1)[0]
    assert "push:" in triggers
    assert "pull_request:" not in triggers
