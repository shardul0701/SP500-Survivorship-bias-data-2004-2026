# Official Membership Refresh Specification

## Native data model

The refresh system preserves the existing `sp500-ticker-changes-YYYY.yaml` model:
`tickers_on_Jan_1`, then effective-date entries with `difference` and `union`.
New automated entries also carry `source_url`, `source_title`, `announcement_date`, and
`confidence_score`. Legacy entries remain unchanged and are reported as provenance warnings.

## Official sources and raw evidence

Only enabled official S&P Global or S&P Dow Jones entries in
`metadata/source_registry.yaml` are accepted. Third-party lists cannot enter the refresh path.
Every downloaded page or PDF is retained under `audit/raw_sources/sp500/`.

## Fail-closed parsing

An update requires an unambiguous S&P 500 reference, effective date, and constituent action.
The parser prefers official S&P summary tables and falls back to narrowly matched replacement
sentences. Unofficial URLs, missing dates, contradictory events, low confidence, and unknown
ticker notation go to `audit/manual_review_required.csv` and never modify YAML.

## Local commands

```bash
python scripts/fetch_official_sp500_announcements.py
python scripts/update_membership_yaml.py --index sp500 --dry-run
python scripts/update_membership_yaml.py --index sp500 --apply
python scripts/validate_membership.py --index sp500
python scripts/audit_membership_update.py
python scripts/check_freshness.py --index sp500
python scripts/validate_yaml.py
```

Default updates are limited to the current year. Historical corrections require
`--correction-mode`, preserve existing membership unless the candidate is explicitly reviewed,
and write `audit/correction_report.md`.

## Validation

Validation covers YAML parsing, duplicates, blanks, logical additions/removals, future pending
changes, year continuity, member-count bounds, ticker notation, and official domains for sourced
entries. Existing unsourced history remains a warning rather than being silently rewritten.

## GitHub Actions and approval

The weekly/manual workflow fetches official sources, performs a dry-run, applies only accepted
candidates, validates, uploads audit artifacts, creates a dated branch, and opens a pull request.
It never pushes directly to `main`. Review every source link, effective date, diff, confidence
score, and manual-review item before merging.

To add a source, register an official S&P URL and parser mode in
`metadata/source_registry.yaml`. Handle parser failures using the saved raw snapshot and a narrow
test; do not broaden patterns until unrelated announcements could be misclassified.
