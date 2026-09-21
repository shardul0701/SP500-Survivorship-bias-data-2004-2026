"""Tests for scripts/validate_running_count.py.

Two halves. The first injects faults into synthetic rosters and asserts each check fires,
with a clean control so the checks are not passing vacuously. The second works on the real
committed data and demonstrates the gap this script exists to close: an unbalanced change,
once propagated forward the way `refresh_lib.py` propagates it, is invisible to the
year-boundary continuity check and visible here.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import validate_running_count as vrc  # noqa: E402
from validate_running_count import (  # noqa: E402
    build_series,
    check_entry_integrity,
    derive_prevailing,
    deviation_episodes,
    load_baseline,
    load_years,
    main,
    prevailing_at,
)

# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------
BASE = [f"T{i:03d}" for i in range(10)]


def _year(year: int, jan1: list[str], changes: dict | None = None) -> dict:
    return {"year": year, "tickers_on_Jan_1": sorted(jan1), "changes": changes or {}}


def _final_membership(data: dict) -> set[str]:
    """Replicates validate_yaml.final_membership / refresh_lib.final_membership."""
    current = set(data.get("tickers_on_Jan_1") or [])
    for key in sorted((data.get("changes") or {}), key=str):
        entry = data["changes"][key] or {}
        current -= set(entry.get("difference") or [])
        current |= set(entry.get("union") or [])
    return current


def _propagate(year_data: dict[int, dict]) -> dict[int, dict]:
    """Mirror refresh_lib.py:1079 — a year's Jan-1 roster is derived from the prior walk.

    This is what makes an unbalanced change permanent and invisible: both sides of the
    continuity comparison move together.
    """
    out = {y: dict(d) for y, d in year_data.items()}
    for y in sorted(out)[:-1]:
        out[y + 1] = {**out[y + 1], "tickers_on_Jan_1": sorted(_final_membership(out[y]))}
    return out


def _clean() -> dict[int, dict]:
    """A balanced two-year roster: one swap per year, count never moves."""
    return {
        2020: _year(2020, BASE, {"2020-06-01": {"difference": ["T000"], "union": ["X001"]}}),
        2021: _year(2021, [t for t in BASE if t != "T000"] + ["X001"],
                    {"2021-06-01": {"difference": ["T001"], "union": ["X002"]}}),
    }


# ---------------------------------------------------------------------------
# [1] Change-entry integrity — each fault, plus a clean control
# ---------------------------------------------------------------------------
def test_clean_synthetic_passes_integrity():
    assert check_entry_integrity(_clean()) == []


def test_phantom_drop_detected():
    data = _clean()
    data[2020]["changes"]["2020-06-01"]["difference"] = ["NOTAMEMBER"]
    errors = check_entry_integrity(data)
    assert any("non-member" in e and "NOTAMEMBER" in e for e in errors), errors


def test_duplicate_add_detected():
    data = _clean()
    data[2020]["changes"]["2020-06-01"]["union"] = ["T005"]  # already a member
    errors = check_entry_integrity(data)
    assert any("existing member" in e and "T005" in e for e in errors), errors


def test_both_direction_ticker_detected():
    data = _clean()
    data[2020]["changes"]["2020-06-01"] = {"difference": ["T000"], "union": ["T000"]}
    errors = check_entry_integrity(data)
    assert any("both difference and union" in e for e in errors), errors


def test_change_date_outside_its_year_detected():
    data = _clean()
    data[2020]["changes"] = {"2019-06-01": {"difference": ["T000"], "union": ["X001"]}}
    errors = check_entry_integrity(data)
    assert any("recorded in the 2020 file" in e for e in errors), errors


def test_unordered_change_keys_detected():
    data = _clean()
    data[2020]["changes"] = {
        "2020-09-01": {"difference": ["T001"], "union": ["X002"]},
        "2020-06-01": {"difference": ["T000"], "union": ["X001"]},
    }
    errors = check_entry_integrity(data)
    assert any("ascending date order" in e for e in errors), errors


# ---------------------------------------------------------------------------
# [3]/[4] Level derivation and deviation measurement
# ---------------------------------------------------------------------------
def test_transient_blip_is_not_a_level():
    """A count that deviates and returns within days is one level, not three."""
    data = {
        2020: _year(2020, BASE, {
            "2020-06-01": {"difference": [], "union": ["X001"]},   # +1, off-level
            "2020-06-04": {"difference": ["T000"], "union": []},   # -1, closed after 3 days
        }),
    }
    series = build_series(data)
    levels = derive_prevailing(series)
    assert [c for _, c in levels] == [10], levels

    episodes = deviation_episodes(series, levels)
    assert len(episodes) == 1
    assert episodes[0].days == 3
    assert episodes[0].peak_offset == 1
    assert not episodes[0].is_open


def test_persistent_step_is_a_level():
    """An unbalanced change that is never compensated becomes a new level."""
    data = {
        2020: _year(2020, BASE, {"2020-02-01": {"difference": [], "union": ["X001"]}}),
        2021: _year(2021, BASE + ["X001"]),
    }
    levels = derive_prevailing(build_series(data))
    assert [c for _, c in levels] == [10, 11], levels
    assert levels[1][0] == dt.date(2020, 2, 1)


def test_deviation_episode_measures_until_it_closes():
    """Duration is time until the count returned, not the span of events at that count."""
    data = {
        2020: _year(2020, BASE, {
            "2020-03-01": {"difference": [], "union": ["X001"]},
            "2020-03-20": {"difference": ["T000"], "union": []},
        }),
    }
    series = build_series(data)
    episodes = deviation_episodes(series, derive_prevailing(series))
    assert len(episodes) == 1 and episodes[0].days == 19


def test_prevailing_at_covers_dates_before_the_first_level():
    levels = [(dt.date(2010, 1, 1), 500), (dt.date(2015, 1, 1), 503)]
    assert prevailing_at(levels, dt.date(2005, 1, 1)) == 500
    assert prevailing_at(levels, dt.date(2012, 1, 1)) == 500
    assert prevailing_at(levels, dt.date(2020, 1, 1)) == 503
    assert prevailing_at([], dt.date(2020, 1, 1)) is None


# ---------------------------------------------------------------------------
# Committed data
# ---------------------------------------------------------------------------
def test_committed_data_passes():
    assert main([]) == 0


def test_baseline_matches_committed_data():
    baseline = load_baseline()
    assert baseline is not None, "metadata/membership_count_baseline.json is missing"
    assert derive_prevailing(build_series(load_years())) == baseline


def test_committed_data_is_on_level_at_head():
    """A clean tail is what makes an open deviation meaningful as a signal."""
    series = build_series(load_years())
    levels = derive_prevailing(series)
    assert series[-1].count == prevailing_at(levels, series[-1].date)
    assert not any(ep.is_open for ep in deviation_episodes(series, levels))


# ---------------------------------------------------------------------------
# The gap this script closes
# ---------------------------------------------------------------------------
def _drop_one_counterpart(year_data: dict[int, dict], year: int) -> tuple[dict, str, str]:
    """Remove one added ticker from a balanced change — a missing counterpart."""
    data = {y: dict(d) for y, d in year_data.items()}
    changes = {k: dict(v) for k, v in (data[year].get("changes") or {}).items()}
    for key in sorted(changes, key=str):
        entry = changes[key]
        added = list(entry.get("union") or [])
        if len(added) >= 1 and (entry.get("difference") or []):
            entry = {**entry, "union": added[1:]}
            changes[key] = entry
            data[year] = {**data[year], "changes": changes}
            return data, str(key), added[0]
    raise AssertionError(f"no balanced change entry found in {year}")


def test_unbalanced_change_in_open_year_creates_a_new_level():
    """The realistic case: a fresh edit in the year being worked on.

    validate_yaml.py cannot see this at all — its continuity loop is YEARS[:-1], so the
    last year has no successor to compare against. Here the shift has held long enough to
    register as a new level, so check [3] names it.
    """
    real = load_years()
    mutated, key, ticker = _drop_one_counterpart(real, 2026)
    series = build_series(mutated)
    levels = derive_prevailing(series)

    assert series[-1].count == 502
    assert levels != load_baseline(), f"dropping {ticker} from {key} left the levels unchanged"
    assert levels[-1] == (dt.date.fromisoformat(key), 502), levels[-1]


def test_recent_unbalanced_change_is_reported_as_still_open():
    """A shift too recent to have persisted is an open deviation, not yet a new level."""
    data = {
        2020: _year(2020, BASE),
        2021: _year(2021, BASE, {"2021-12-20": {"difference": ["T000"], "union": []}}),
    }
    series = build_series(data)
    levels = derive_prevailing(series)
    assert [c for _, c in levels] == [10], levels

    episodes = deviation_episodes(series, levels)
    assert len(episodes) == 1
    assert episodes[0].is_open
    assert episodes[0].peak_offset == -1


def test_unbalanced_change_propagated_forward_corrupts_the_level_series():
    """The same fault in an earlier year, propagated as the pipeline propagates it.

    It does not necessarily shift the level forever: ENDP is added 2015-01-27 and dropped
    2017-03-02, so removing the add turns that later drop into a no-op and the count
    rejoins its true path. The level series is wrong across the span in between, and the
    now-phantom drop is independently caught by the integrity check — which is why a
    count-only rule is not sufficient on its own.
    """
    real = load_years()
    mutated, key, ticker = _drop_one_counterpart(real, 2015)
    mutated = _propagate(mutated)

    levels = derive_prevailing(build_series(mutated))
    baseline = load_baseline()
    assert levels != baseline, f"dropping {ticker} from {key} did not change the level series"

    mutation_date = dt.date.fromisoformat(key)
    assert any(eff == mutation_date for eff, _ in levels), levels
    # every level between the mutation and the ticker's later drop sits one low
    corrupted = [(eff, c) for eff, c in levels
                 if mutation_date <= eff <= dt.date(2017, 3, 2)]
    assert corrupted, levels
    for eff, count in corrupted:
        assert (eff, count) not in baseline, (eff, count)

    errors = check_entry_integrity(mutated)
    assert any("non-member" in e and ticker in e for e in errors), errors


def test_year_boundary_check_alone_misses_the_propagated_defect():
    """Why the running-count check is needed: continuity compares derived to derived.

    refresh_lib.py:1079 builds a year's Jan-1 roster from the previous year's walk, so once
    the fault is propagated both sides of `final_membership(Y) == tickers_on_Jan_1(Y+1)`
    agree and every year boundary passes — while the running count is permanently wrong.
    """
    real = load_years()
    mutated, _key, _ticker = _drop_one_counterpart(real, 2015)
    mutated = _propagate(mutated)

    years = sorted(mutated)
    for left, right in zip(years, years[1:]):
        expected = _final_membership(mutated[left])
        actual = set(mutated[right].get("tickers_on_Jan_1") or [])
        assert expected == actual, f"continuity {left}->{right} should pass after propagation"

    # ...and yet the level is wrong.
    assert derive_prevailing(build_series(mutated)) != load_baseline()


# ---------------------------------------------------------------------------
# The CI entry point, end to end on a synthetic repo
# ---------------------------------------------------------------------------
def _write_repo(root: Path, year_data: dict[int, dict]) -> Path:
    yaml_dir = root / "src" / "sp500_ticker_history"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    for year, data in year_data.items():
        with open(yaml_dir / f"sp500-ticker-changes-{year}.yaml", "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)
    return yaml_dir


def test_main_end_to_end_on_a_synthetic_repo(tmp_path, monkeypatch, capsys):
    """The lifecycle CI exercises: no baseline FAILs, --update-baseline accepts, then PASSes.

    Also pins --strict: a fresh unbalanced change is a WARN (exit 0) by default, because a
    real edit cannot yet be told apart from a genuine re-size, and a FAIL under --strict.
    """
    data = _clean()
    yaml_dir = _write_repo(tmp_path, data)
    baseline = tmp_path / "metadata" / "membership_count_baseline.json"

    monkeypatch.setattr(vrc, "YAML_DIR", yaml_dir)
    monkeypatch.setattr(vrc, "BASELINE_PATH", baseline)
    monkeypatch.setattr(vrc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(vrc, "YEARS", sorted(data))

    # a missing baseline is a failure, not a silent pass
    assert vrc.main([]) == 1
    assert "no baseline" in capsys.readouterr().out
    assert not baseline.exists()

    # generating it is how a level is accepted
    assert vrc.main(["--update-baseline"]) == 0
    assert baseline.exists()
    assert json.loads(baseline.read_text(encoding="utf-8"))["levels"] == [
        {"from": "2020-01-01", "count": 10}
    ]
    capsys.readouterr()

    # and now the clean roster passes every check — all five, not just the banner
    assert vrc.main([]) == 0
    out = capsys.readouterr().out
    assert "ALL CHECKS PASSED" in out
    passes = [ln for ln in out.splitlines() if ln.startswith("  ") and "PASS" in ln]
    assert len(passes) == 5, passes

    # a fresh unbalanced change in the open year: WARN by default, FAIL under --strict
    data[2021]["changes"]["2021-12-20"] = {"difference": ["T002"], "union": []}
    _write_repo(tmp_path, data)
    assert vrc.main([]) == 0
    assert "deviation still OPEN" in capsys.readouterr().out
    assert vrc.main(["--strict"]) == 1
    assert "SOME CHECKS FAILED" in capsys.readouterr().out
