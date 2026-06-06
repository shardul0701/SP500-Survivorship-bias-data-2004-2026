from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from refresh_lib import parse_announcement


def test_sp500_summary_table_parser():
    html = b"""
    <html><head><meta property="article:published_time" content="2026-06-05"/></head>
    <body><table>
      <tr><th>Effective Date</th><th>Index Name</th><th>Action</th><th>Company Name</th><th>Ticker</th></tr>
      <tr><td>June 12, 2026</td><td>S&amp;P 500</td><td>Addition</td><td>Marvell</td><td>MRVL</td></tr>
      <tr><td>June 12, 2026</td><td>S&amp;P 500</td><td>Deletion</td><td>Company</td><td>DAY</td></tr>
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
    assert changes[0].added_tickers == ["MRVL"]
    assert changes[0].removed_tickers == ["DAY"]
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
