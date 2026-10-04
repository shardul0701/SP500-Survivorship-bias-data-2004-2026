# Official Membership Refresh Specification

## Native data model

The refresh system preserves the existing `sp500-ticker-changes-YYYY.yaml` model:
`tickers_on_Jan_1`, then effective-date entries with `difference` and `union`.
New automated entries also carry `source_url`, `source_title`, `announcement_date`, and
`confidence_score`. Legacy entries remain unchanged and are reported as provenance warnings.

### Events with no press release

S&P DJI does not announce a ticker change, because the security and its index seat do not
change. The crawler therefore never sees one, but the YAML is keyed by ticker, so a consumer
asking for the new symbol gets nothing until the rename is recorded. A rename is entered by hand
as a `difference` of the old ticker and a `union` of the new one on the effective date, with
`evidence_url` and `evidence_note` in place of `source_url`. Enter it only once the new symbol
appears in the live holdings (see below):

```yaml
  '2026-05-21':
    difference:
      - BK
    union:
      - BNY
    evidence_url: https://www.bny.com/corporate/global/en/about-us/newsroom/press-release/...
    evidence_note: 'Ticker change only: The Bank of New York Mellon Corporation moved its NYSE
      symbol from BK to BNY effective 2026-05-21 (announced 2026-05-11). ...'
    announcement_date: '2026-05-11'
```

A rename can share its date with an announced change. On 2026-08-18 AvalonBay left the index
for Reddit (an S&P release), and on the same day Equity Residential renamed itself Vivmark
Residential (EQR to VMRK, no S&P release). Both go in one entry: the S&P release stays as
`source_url` and `evidence_url` documents the rename. The planner treats an entry as covering a
release when the tickers match exactly, or when the entry holds a superset of the release's
tickers *and* has an `evidence_url`. A superset with no evidence is still reported as a
contradiction, so an unexplained hand edit is not accepted silently.

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
python scripts/check_live_constituents.py --index sp500
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

## Live constituent check

The release crawler only finds changes S&P announces in a press release. Three 2026 ticker
changes (BK to BNY, SATS to ECHO, EQR to VMRK) were never recorded that way, and nothing
noticed because the YAML still validated. `scripts/live_check.py` closes that gap by comparing
the YAML with what the index actually holds:

```bash
python scripts/check_live_constituents.py --index sp500          # writes metadata/live_check_state.json
python scripts/check_live_constituents.py --index sp500 --gate   # exit 1 if it needs attention
```

- The source is State Street's daily SPY holdings file (`ssga.com`,
  `holdings-daily-us-en-spy.xlsx`). SPY fully replicates the index, so its holdings are the
  S&P 500 as of the file's "As of" date. Cash and non-ticker rows are dropped.
- The comparison is by name, not count, so a one-for-one swap is caught. Share-class notation
  is normalised before comparing (`BF.B`, `BF-B` and `BF/B` are one name).
- A name is reported only if it disagrees on every weekday from one day before to two days
  after the file's as-of date. That absorbs a holdings file that moves a day early or late
  without hiding a change that is simply missing.
- An unreachable or unparseable file is `source_error`. It fails the gate only once there has
  been no pass for three days, so one bad fetch does not page anyone.
- `check_freshness.py` reads the state: confidence is not `high` unless the last live check
  passed within four days.

## Alerts

Two conditions open a GitHub issue (label `live-check` or `manual-review`), refresh it while
the condition holds, comment only when the condition changes, and close it once the condition
clears. Every write is read back and compared; a body that does not round-trip is an error.

- `check_live_constituents.py --alert`: the live check disagrees with the YAML.
- `alert_manual_review.py --alert`: a fetched release in `audit/manual_review_required.csv`
  is neither recorded in the YAML (by `source_url` or `evidence_url`) nor acknowledged in
  `metadata/manual_review_ack.yaml`. Previously this CSV was read only when a PR opened, so
  a release that produced no YAML change was never seen.

Acknowledge a release only when it is not a membership change, and give the reason.

## Year-file housekeeping

`scripts/rollover_year.py` runs before every refresh and does two things:

- `tickers_as_of` needs a file for the year it is asked about. On the first run of a new year
  it creates that year's file from the previous year's final membership with empty `changes`,
  and does nothing otherwise.
- A change applied before its effective date is marked `pending: true`. Once the date arrives
  the flag is removed; nothing used to remove it, so past changes kept claiming to be future
  ones.

## GitHub Actions and approval

`.github/workflows/refresh_membership.yml` runs every weekday and on demand. It runs the
year-file housekeeping, fetches, plans, applies only high-confidence candidates, validates, runs
the live check and the manual-review alert, checks freshness, and uploads audit artifacts.
Derived metadata and audit reports are committed straight to `main`. A membership change goes
through a pull request, which the run merges itself unless a manual-review release is still
outstanding (neither recorded nor acknowledged); then the PR is labelled `needs-human-review`
and left open. The last steps fail the run red when the live check needs attention, an alert
could not be raised, or the dataset is stale.

Change detection uses `git status --porcelain`, not `git diff --quiet`, because a newly
created year file is untracked and `git diff` does not see it.

Review the source links, effective dates, diff report, confidence report, manual-review CSV,
validation report, and freshness report before merging a PR that was left open.

To add a source, register an official S&P URL and parser mode in
`metadata/source_registry.yaml`. Handle parser failures using the saved raw snapshot and a narrow
test; do not broaden patterns until unrelated announcements could be misclassified.
