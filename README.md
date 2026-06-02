# SP500-Survivorship-bias-data-2004-2026

Point-in-time S&P 500 constituent data from 2004 to 2026, in canonical YAML format.
Designed for survivorship-bias-free backtesting of US equity strategies.

## What this is

Each year has a YAML file under `src/sp500_ticker_history/` recording:
- The exact list of S&P 500 members on January 1 of that year
- Every date within the year where membership changed (additions and removals)

This allows you to reconstruct the exact S&P 500 universe on any date, including
tickers that were later removed — eliminating survivorship bias.

**Data coverage:** Source CSV covers 1996-01-02 through 2019-01-11.
YAML files for 2020-2026 carry forward the last known 2019 membership (no change entries).

## Usage

### Get the S&P 500 universe as of any date

```python
from scripts.build_universe import get_universe_as_of

tickers = get_universe_as_of("2015-06-01")
# Returns sorted list like ['A', 'AAL', 'AAPL', ...]
print(f"S&P 500 on 2015-06-01: {len(tickers)} members")
```

### Get all tickers ever in the index

```python
from scripts.build_universe import get_all_historical_tickers

all_time = get_all_historical_tickers()
print(f"Total unique tickers 2004-2026: {len(all_time)}")
```

### Command-line lookup

```bash
python scripts/build_universe.py 2015-06-01
python scripts/build_universe.py --all
```

## Validate the dataset

```bash
python scripts/validate_yaml.py
```

Checks: YAML parses correctly, no duplicate tickers, member counts in valid range
(450-560), year-to-year continuity, no empty change entries.

## Run the membership audit

```bash
python scripts/audit_membership.py
```

Prints and saves to `audit/audit_report.txt`:
- Jan 1 member count per year
- Total additions/removals per year
- Top 5 largest single-day changes
- Total unique tickers ever in the index

## Regenerate YAML from source

```bash
python scripts/convert_from_fja05680.py
```

Reads `source_raw/S&P 500 Historical Components & Changes.csv` and writes all 23
YAML files to `src/sp500_ticker_history/`.

## YAML format

```yaml
year: 2010

tickers_on_Jan_1:
  - A
  - AAPL
  - ABT
  ...

changes:

  '2010-03-15':
    difference:
      - GGP
    union:
      - FLIR
```

- `tickers_on_Jan_1`: S&P 500 membership on the last trading day of the prior year
- `changes`: dates where membership changed; `difference` = removed, `union` = added
- All ticker lists are sorted alphabetically

## Data source

Original data from [fja05680/sp500](https://github.com/fja05680/sp500) (MIT License).
See `licenses/fja05680_sp500_LICENSE` and `source_notes.json` for details.

## Directory structure

```
SP500-Survivorship-bias-data-2004-2026/
├── src/sp500_ticker_history/     # 23 YAML files (one per year)
├── scripts/
│   ├── convert_from_fja05680.py  # Regenerate YAML from source CSV
│   ├── build_universe.py         # Point-in-time universe API
│   ├── validate_yaml.py          # Dataset validation
│   └── audit_membership.py       # Membership audit report
├── source_raw/                   # Original source CSV
├── audit/                        # Audit output (git-ignored)
├── licenses/                     # Data license attribution
├── source_notes.json             # Provenance metadata
└── requirements.txt              # pyyaml, pandas
```
