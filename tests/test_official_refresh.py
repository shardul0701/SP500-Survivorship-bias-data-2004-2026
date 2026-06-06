from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_lib import (
    discover_archive_history,
    normalize_ticker_cell,
    parse_announcement,
    press_release_date,
)


def test_sp500_summary_table_parser():
    html = b"""
    <html><head><meta property="article:published_time" content="2026-06-05"/></head>
    <body><table>
      <tr><th>Effective Date</th><th>Index Name</th><th>Action</th><th>Company Name</th><th>Ticker</th></tr>
      <tr><td>June 12, 2026</td><td>S&amp;P 500</td><td>Addition</td><td>Marvell</td><td>MRVL</td></tr>
      <tr><td></td><td>S&amp;P 500</td><td>Addition</td><td>Flex</td><td>FLEX</td></tr>
      <tr><td></td><td>S&amp;P 500</td><td>Deletion</td><td>Companies</td><td>CPB/POOL</td></tr>
    </table></body></html>
    """
    changes = parse_announcement(
        "sp500",
        html,
        "S&P 500 constituent changes effective June 12, 2026.",
        "https://press.spglobal.com/example",
        "Marvell Set to Join S&P 500",
    )
    assert changes[0].effective_date == "2026-06-12"
    assert changes[0].added_tickers == ["FLEX", "MRVL"]
    assert changes[0].removed_tickers == ["CPB", "POOL"]
    assert not changes[0].manual_review_required


def test_unofficial_source_fails_closed():
    changes = parse_announcement(
        "sp500",
        b"<html></html>",
        "Company will join the S&P 500.",
        "https://example.com/list",
        "Unofficial list",
    )
    assert changes[0].manual_review_required
    assert changes[0].confidence_score == 0.0


def test_old_format_replacement_prose_parser():
    text = (
        "NEW YORK, May 6, 2020. Changes are effective prior to the opening on "
        "Tuesday, May 12. DexCom Inc. (NASD:DXCM) will replace Allergan plc "
        "(NYSE:AGN) in the S&P 500. S&P MidCap 400 constituent Domino's Pizza "
        "Inc. (NYSE:DPZ) will replace Capri Holdings Ltd. (NYSE:CPRI) in the "
        "S&P 500."
    )
    changes = parse_announcement(
        "sp500",
        b"<html></html>",
        text,
        "https://press.spglobal.com/2020-05-06-example",
        "DexCom and Domino's Pizza Set to Join S&P 500",
    )
    assert changes[0].effective_date == "2020-05-12"
    assert changes[0].added_tickers == ["DPZ", "DXCM"]
    assert changes[0].removed_tickers == ["AGN", "CPRI"]
    assert not changes[0].manual_review_required


def test_press_release_date_parses_official_url():
    value = press_release_date(
        "https://press.spglobal.com/2024-06-07-Company-Set-to-Join-S-P-500"
    )
    assert value.isoformat() == "2024-06-07"


def test_multi_ticker_table_cell_is_split():
    assert normalize_ticker_cell("UA, UAA", {}) == ["UA", "UAA"]


def test_archive_history_filters_dates_and_stops(monkeypatch, tmp_path):
    pages = {
        0: b"""
            <a href="/2026-01-02-New-Co-Set-to-Join-S-P-500">New Co Set to Join S&amp;P 500</a>
            <a href="/2025-12-02-In-Co-Set-to-Join-S-P-500">In Co Set to Join S&amp;P 500</a>
        """,
        100: b"""
            <a href="/2025-01-02-Old-Co-Set-to-Join-S-P-500">Old Co Set to Join S&amp;P 500</a>
            <a href="/2024-12-31-Older-Co-Set-to-Join-S-P-500">Older Co Set to Join S&amp;P 500</a>
        """,
    }

    class Response:
        status_code = 200
        headers = {"content-type": "text/html"}

        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, timeout):
            offset = int(url.split("o=")[1].split("&")[0])
            return Response(pages[offset])

    monkeypatch.setattr("refresh_lib.RAW_DIR", tmp_path)
    found, errors, count = discover_archive_history(
        Session(),
        "sp500",
        "https://press.spglobal.com/index.php?s=2429",
        date(2025, 1, 1),
        date(2025, 12, 31),
        page_size=100,
    )
    assert count == 2
    assert not errors
    assert sorted(press_release_date(url).isoformat() for url in found) == [
        "2025-01-02",
        "2025-12-02",
    ]
