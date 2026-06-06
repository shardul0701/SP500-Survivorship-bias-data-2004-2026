"""Official-source PIT membership refresh helpers.

The two membership repositories intentionally keep their existing YAML schema:

    year
    tickers_on_Jan_1
    changes.<effective date>.difference / union

New automated changes add source metadata beside ``difference`` and ``union``.
Legacy entries are never rewritten merely to satisfy the new metadata policy.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from pypdf import PdfReader
from ruamel.yaml import YAML

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass


ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "audit"
RAW_DIR = AUDIT_DIR / "raw_sources"
METADATA_DIR = ROOT / "metadata"

CANDIDATE_FIELDS = [
    "index_name",
    "announcement_date",
    "effective_date",
    "added_tickers",
    "removed_tickers",
    "source_url",
    "source_title",
    "raw_file_path",
    "confidence_score",
    "parser_notes",
    "manual_review_required",
]
MANUAL_FIELDS = CANDIDATE_FIELDS + ["review_reason"]

INDEX_PROFILES = {
    "nq100": {
        "index_name": "Nasdaq-100",
        "data_dir": ROOT / "src" / "nasdaq_100_ticker_history",
        "filename": "n100-ticker-changes-{year}.yaml",
        "glob": "n100-ticker-changes-*.yaml",
        "min_members": 95,
        "max_members": 110,
        "candidate_file": AUDIT_DIR / "nq100_official_candidates.csv",
        "official_domains": {
            "nasdaq.com",
            "www.nasdaq.com",
            "ir.nasdaq.com",
            "indexes.nasdaq.com",
            "indexes.nasdaqomx.com",
        },
    },
    "sp500": {
        "index_name": "S&P 500",
        "data_dir": ROOT / "src" / "sp500_ticker_history",
        "filename": "sp500-ticker-changes-{year}.yaml",
        "glob": "sp500-ticker-changes-*.yaml",
        "min_members": 450,
        "max_members": 560,
        "candidate_file": AUDIT_DIR / "sp500_official_candidates.csv",
        "official_domains": {
            "spglobal.com",
            "www.spglobal.com",
            "press.spglobal.com",
        },
    },
}

MONTH_DATE = (
    r"(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+20\d{2}"
)
SHORT_MONTH_DATE = (
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember)?\.?\s+\d{1,2},\s+20\d{2}"
)
DATE_PATTERN = re.compile(rf"\b{MONTH_DATE}\b", re.IGNORECASE)
TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")
EXCHANGE_TICKER_PATTERN = re.compile(
    r"\((?:Nasdaq|NYSE|NASD|NYSE American)\s*:\s*([A-Z][A-Z0-9.\-/]{0,11})\)",
    re.IGNORECASE,
)


@dataclass
class ParsedChange:
    index_name: str
    announcement_date: str
    effective_date: str
    added_tickers: list[str]
    removed_tickers: list[str]
    source_url: str
    source_title: str
    confidence_score: float
    parser_notes: str
    manual_review_required: bool = False

    def row(self, raw_file_path: str) -> dict[str, str]:
        return {
            "index_name": self.index_name,
            "announcement_date": self.announcement_date,
            "effective_date": self.effective_date,
            "added_tickers": ";".join(self.added_tickers),
            "removed_tickers": ";".join(self.removed_tickers),
            "source_url": self.source_url,
            "source_title": self.source_title,
            "raw_file_path": raw_file_path,
            "confidence_score": f"{self.confidence_score:.2f}",
            "parser_notes": self.parser_notes,
            "manual_review_required": str(self.manual_review_required).lower(),
        }


def profile(index: str) -> dict:
    key = index.lower()
    if key not in INDEX_PROFILES:
        raise ValueError(f"Unsupported index {index!r}; expected nq100 or sp500")
    result = dict(INDEX_PROFILES[key])
    if not result["data_dir"].exists():
        raise FileNotFoundError(
            f"This repository does not contain the {key} YAML directory: "
            f"{result['data_dir']}"
        )
    result["key"] = key
    return result


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().replace(microsecond=0).isoformat()


def load_registry() -> dict:
    path = METADATA_DIR / "source_registry.yaml"
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data.get("sources"), list):
        raise ValueError("metadata/source_registry.yaml must contain a sources list")
    return data


def load_ticker_mapping() -> dict[str, str]:
    path = METADATA_DIR / "ticker_mapping.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return {
        str(key).upper(): str(value).upper()
        for key, value in (data.get("aliases") or {}).items()
    }


def normalize_ticker(raw: str, aliases: dict[str, str]) -> str | None:
    ticker = raw.strip().upper().replace("/", ".")
    ticker = aliases.get(ticker, ticker)
    return ticker if TICKER_PATTERN.fullmatch(ticker) else None


def official_url(url: str, allowed_domains: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in allowed_domains


def request_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "PITMembershipRefresh/1.0 "
                "(official-source audit; https://github.com/shardul0701)"
            )
        }
    )
    return session


def fetch_url(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=45)
    response.raise_for_status()
    return response


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug[:100] or "source"


def save_raw(index: str, url: str, content: bytes, content_type: str) -> Path:
    target_dir = RAW_DIR / index
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    suffix = ".pdf" if "pdf" in content_type.lower() or url.lower().endswith(".pdf") else ".html"
    name = f"{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{digest}-{safe_slug(Path(urlparse(url).path).name)}"
    path = target_dir / f"{name}{suffix}"
    path.write_bytes(content)
    return path


def text_from_content(content: bytes, content_type: str, raw_path: Path) -> tuple[str, str]:
    if raw_path.suffix.lower() == ".pdf" or "pdf" in content_type.lower():
        try:
            reader = PdfReader(str(raw_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages), "pdf"
        except Exception as exc:
            return "", f"pdf extraction failed: {exc}"
    soup = BeautifulSoup(content, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return soup.get_text("\n", strip=True), "html"


def discover_links(index: str, html: bytes, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, str] = {}
    if index == "nq100":
        title_pattern = re.compile(
            r"(Nasdaq[- ]100).*(join|change|reconstitution|replace)|"
            r"(join|change|reconstitution|replace).*(Nasdaq[- ]100)",
            re.IGNORECASE,
        )
    else:
        title_pattern = re.compile(
            r"(S&P|S-P)\s*500.*(join|add|replace|change)|"
            r"(join|add|replace|change).*(S&P|S-P)\s*500",
            re.IGNORECASE,
        )
    for anchor in soup.find_all("a", href=True):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        href = urljoin(base_url, anchor["href"])
        if title and title_pattern.search(title):
            found[href] = title
    return sorted(found.items())


def parse_date_value(value: str, default_year: int | None = None) -> str:
    parsed = date_parser.parse(value, fuzzy=True, default=datetime(default_year or 2000, 1, 1))
    return parsed.date().isoformat()


def announcement_date_from_html(html: bytes, text: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for attrs in (
        {"property": "article:published_time"},
        {"name": "date"},
        {"name": "Date"},
    ):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            try:
                return parse_date_value(tag["content"])
            except Exception:
                pass
    dateline = re.search(
        rf"\b(?:NEW YORK|PHILADELPHIA|SAN FRANCISCO|LONDON)\s*,?\s*({SHORT_MONTH_DATE})",
        text,
        re.IGNORECASE,
    )
    if dateline:
        return parse_date_value(dateline.group(1))
    heading_date = re.search(
        rf"\b{SHORT_MONTH_DATE}\b",
        text[:1500],
        re.IGNORECASE,
    )
    if heading_date:
        return parse_date_value(heading_date.group(0))
    match = DATE_PATTERN.search(text[:3000])
    return parse_date_value(match.group(0)) if match else ""


def effective_dates(text: str, announcement_date: str) -> list[str]:
    phrases = re.findall(
        r"(?:effective|prior to (?:the )?(?:market )?open(?:ing of trading)?|"
        r"before (?:the )?(?:market )?open|after (?:the )?close)"
        rf"[^.\n]{{0,140}}?({MONTH_DATE})",
        text,
        flags=re.IGNORECASE,
    )
    dates = []
    for phrase in phrases:
        try:
            parsed = parse_date_value(phrase)
            if parsed not in dates:
                dates.append(parsed)
        except Exception:
            continue
    if not dates:
        short_dates = re.findall(
            r"(?:effective|prior to (?:the )?(?:market )?open(?:ing of trading)?|"
            r"before (?:the )?(?:market )?open|after (?:the )?close)"
            r"[^.\n]{0,100}?\b("
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
            r"(?:uary|ruary|ch|il|e|y|ust|tember|ober|ember)?\.?\s+\d{1,2})\b",
            text,
            flags=re.IGNORECASE,
        )
        year = int(announcement_date[:4]) if announcement_date else utc_now().year
        for phrase in short_dates:
            try:
                value = parse_date_value(phrase, default_year=year)
                if value not in dates:
                    dates.append(value)
            except Exception:
                continue
    return dates


def _tickers_in_section(text: str, start_pattern: str, end_pattern: str) -> list[str]:
    match = re.search(start_pattern + r"(?P<body>.*?)" + end_pattern, text, re.IGNORECASE | re.DOTALL)
    return EXCHANGE_TICKER_PATTERN.findall(match.group("body")) if match else []


def parse_nq100(
    html: bytes,
    text: str,
    source_url: str,
    title: str,
    aliases: dict[str, str],
) -> list[ParsedChange]:
    announcement_date = announcement_date_from_html(html, text)
    dates = effective_dates(text, announcement_date)
    added = _tickers_in_section(
        text,
        r"(?:following\s+\w+\s+companies\s+will\s+be\s+added|"
        r"companies\s+will\s+be\s+added|will\s+be\s+added\s+to\s+the\s+Index)\s*:?",
        r"(?:As a result|The Nasdaq-100 Index|Information|About Nasdaq)",
    )
    removed = _tickers_in_section(
        text,
        r"(?:following\s+\w+\s+companies\s+will\s+be\s+removed|"
        r"companies\s+will\s+be\s+removed)\s*:?",
        r"(?:Information|About Nasdaq|Media Relations)",
    )

    replacement = re.search(
        r"(?P<before>[^.]{0,500}?)(?:will become|will be added|will join)"
        r"[^.]{0,220}?replac(?:e|ing)(?P<after>[^.]{0,250})",
        text,
        re.IGNORECASE,
    )
    if replacement:
        before_tickers = EXCHANGE_TICKER_PATTERN.findall(replacement.group("before"))
        after_tickers = EXCHANGE_TICKER_PATTERN.findall(replacement.group("after"))
        if before_tickers:
            added.append(before_tickers[-1])
        if after_tickers:
            removed.append(after_tickers[0])

    normalized_add = sorted(
        {value for raw in added if (value := normalize_ticker(raw, aliases))}
    )
    normalized_remove = sorted(
        {value for raw in removed if (value := normalize_ticker(raw, aliases))}
    )
    overlap = sorted(set(normalized_add) & set(normalized_remove))
    date_value = dates[0] if len(dates) == 1 else ""
    reasons = []
    if not date_value:
        reasons.append("effective date missing or ambiguous")
    if not normalized_add and not normalized_remove:
        reasons.append("no confident add/remove tickers")
    if overlap:
        reasons.append(f"same ticker added and removed: {','.join(overlap)}")
    confidence = 0.98 if not reasons and normalized_add and normalized_remove else 0.92 if not reasons else 0.40
    return [
        ParsedChange(
            index_name="Nasdaq-100",
            announcement_date=announcement_date,
            effective_date=date_value,
            added_tickers=normalized_add,
            removed_tickers=normalized_remove,
            source_url=source_url,
            source_title=title,
            confidence_score=confidence,
            parser_notes="; ".join(reasons) or "official Nasdaq announcement parsed",
            manual_review_required=bool(reasons),
        )
    ]


def _sp500_table_events(
    html: bytes, announcement_date: str, source_url: str, title: str, aliases: dict[str, str]
) -> list[ParsedChange]:
    soup = BeautifulSoup(html, "html.parser")
    grouped: dict[str, dict[str, list[str]]] = {}
    for table in soup.find_all("table"):
        rows = [
            [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["th", "td"])]
            for row in table.find_all("tr")
        ]
        if not rows:
            continue
        headers = [cell.lower() for cell in rows[0]]
        required = {"effective date", "index name", "action", "ticker"}
        if not required.issubset(set(headers)):
            continue
        positions = {name: headers.index(name) for name in required}
        for row in rows[1:]:
            if len(row) <= max(positions.values()):
                continue
            if row[positions["index name"]].strip().lower() not in {"s&p 500", "s & p 500"}:
                continue
            try:
                eff = parse_date_value(
                    row[positions["effective date"]],
                    default_year=int(announcement_date[:4]) if announcement_date else utc_now().year,
                )
            except Exception:
                continue
            ticker = normalize_ticker(row[positions["ticker"]], aliases)
            if not ticker:
                continue
            action = row[positions["action"]].lower()
            bucket = grouped.setdefault(eff, {"added": [], "removed": []})
            if "add" in action:
                bucket["added"].append(ticker)
            elif "delet" in action or "remov" in action:
                bucket["removed"].append(ticker)
    return [
        ParsedChange(
            index_name="S&P 500",
            announcement_date=announcement_date,
            effective_date=effective_date,
            added_tickers=sorted(set(values["added"])),
            removed_tickers=sorted(set(values["removed"])),
            source_url=source_url,
            source_title=title,
            confidence_score=0.99,
            parser_notes="official S&P summary table parsed",
        )
        for effective_date, values in sorted(grouped.items())
        if values["added"] or values["removed"]
    ]


def parse_sp500(
    html: bytes,
    text: str,
    source_url: str,
    title: str,
    aliases: dict[str, str],
) -> list[ParsedChange]:
    announcement_date = announcement_date_from_html(html, text)
    table_events = _sp500_table_events(html, announcement_date, source_url, title, aliases)
    if table_events:
        return table_events

    dates = effective_dates(text, announcement_date)
    additions: list[str] = []
    removals: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if "S&P 500" not in sentence:
            continue
        tickers = EXCHANGE_TICKER_PATTERN.findall(sentence)
        if len(tickers) < 2 or not re.search(r"\bwill replace\b", sentence, re.IGNORECASE):
            continue
        additions.append(tickers[0])
        removals.append(tickers[1])
    normalized_add = sorted(
        {value for raw in additions if (value := normalize_ticker(raw, aliases))}
    )
    normalized_remove = sorted(
        {value for raw in removals if (value := normalize_ticker(raw, aliases))}
    )
    reasons = []
    if len(dates) != 1:
        reasons.append("effective date missing or ambiguous")
    if not normalized_add or not normalized_remove:
        reasons.append("S&P 500 replacement pair not confidently parsed")
    overlap = sorted(set(normalized_add) & set(normalized_remove))
    if overlap:
        reasons.append(f"same ticker added and removed: {','.join(overlap)}")
    return [
        ParsedChange(
            index_name="S&P 500",
            announcement_date=announcement_date,
            effective_date=dates[0] if len(dates) == 1 else "",
            added_tickers=normalized_add,
            removed_tickers=normalized_remove,
            source_url=source_url,
            source_title=title,
            confidence_score=0.95 if not reasons else 0.40,
            parser_notes="; ".join(reasons) or "official S&P replacement sentence parsed",
            manual_review_required=bool(reasons),
        )
    ]


def parse_announcement(
    index: str, html: bytes, text: str, source_url: str, title: str
) -> list[ParsedChange]:
    prof = profile(index)
    if not official_url(source_url, prof["official_domains"]):
        return [
            ParsedChange(
                index_name=prof["index_name"],
                announcement_date="",
                effective_date="",
                added_tickers=[],
                removed_tickers=[],
                source_url=source_url,
                source_title=title,
                confidence_score=0.0,
                parser_notes="source domain is not official",
                manual_review_required=True,
            )
        ]
    text = " ".join(text.split())
    aliases = load_ticker_mapping()
    if index == "nq100":
        return parse_nq100(html, text, source_url, title, aliases)
    return parse_sp500(html, text, source_url, title, aliases)


def document_title(html: bytes, fallback: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return " ".join(og["content"].split())
    heading = soup.find("h1")
    if heading:
        return " ".join(heading.get_text(" ", strip=True).split())
    if soup.title:
        return " ".join(soup.title.get_text(" ", strip=True).split())
    return fallback


def write_csv(path: Path, rows: Iterable[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fetch_official_candidates(index: str) -> list[dict[str, str]]:
    prof = profile(index)
    registry = load_registry()
    sources = [
        source
        for source in registry["sources"]
        if source.get("enabled", True)
        and source.get("official_source") is True
        and source.get("index_name") == prof["index_name"]
    ]
    session = request_session()
    discovered: dict[str, str] = {}
    fetch_errors: list[str] = []
    successful_fetches = 0
    for source in sources:
        urls = [
            (
                source["source_url"],
                source.get("source_name", source["source_url"]),
                source.get("discovery", False),
            )
        ]
        urls.extend(
            (url, source.get("source_name", url), False)
            for url in source.get("seed_urls", [])
        )
        for url, fallback_title, is_discovery in urls:
            if not official_url(url, prof["official_domains"]):
                fetch_errors.append(f"registry rejected unofficial URL: {url}")
                continue
            try:
                response = fetch_url(session, url)
                successful_fetches += 1
                raw = save_raw(index, url, response.content, response.headers.get("content-type", ""))
                if is_discovery:
                    for link, title in discover_links(index, response.content, url):
                        if official_url(link, prof["official_domains"]):
                            discovered[link] = title
                else:
                    discovered[url] = fallback_title
                _ = raw
            except Exception as exc:
                fetch_errors.append(f"{url}: {exc}")

    rows: list[dict[str, str]] = []
    manual_rows: list[dict[str, str]] = []
    for url, title in sorted(discovered.items()):
        try:
            response = fetch_url(session, url)
            content_type = response.headers.get("content-type", "")
            raw_path = save_raw(index, url, response.content, content_type)
            text, extraction_note = text_from_content(response.content, content_type, raw_path)
            resolved_title = document_title(response.content, title)
            changes = parse_announcement(index, response.content, text, url, resolved_title)
            for change in changes:
                change.parser_notes = f"{change.parser_notes}; extracted={extraction_note}"
                row = change.row(str(raw_path.relative_to(ROOT)))
                rows.append(row)
                if change.manual_review_required:
                    manual_rows.append({**row, "review_reason": change.parser_notes})
        except Exception as exc:
            row = {
                "index_name": prof["index_name"],
                "announcement_date": "",
                "effective_date": "",
                "added_tickers": "",
                "removed_tickers": "",
                "source_url": url,
                "source_title": title,
                "raw_file_path": "",
                "confidence_score": "0.00",
                "parser_notes": f"fetch/parse failed: {exc}",
                "manual_review_required": "true",
            }
            rows.append(row)
            manual_rows.append({**row, "review_reason": row["parser_notes"]})

    write_csv(prof["candidate_file"], rows, CANDIDATE_FIELDS)
    existing_manual = [
        row for row in read_csv(AUDIT_DIR / "manual_review_required.csv")
        if row.get("index_name") != prof["index_name"]
    ]
    write_csv(
        AUDIT_DIR / "manual_review_required.csv",
        existing_manual + manual_rows,
        MANUAL_FIELDS,
    )
    state = {
        "index_name": prof["index_name"],
        "fetched_at": iso_now(),
        "sources_attempted": len(sources),
        "candidate_urls": len(discovered),
        "parsed_candidates": len(rows),
        "manual_review_items": len(manual_rows),
        "errors": fetch_errors,
        "successful_fetches": successful_fetches,
        "successful": successful_fetches > 0,
    }
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    (METADATA_DIR / f"{index}_fetch_state.json").write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )
    return rows


def yaml_rt() -> YAML:
    parser = YAML()
    parser.preserve_quotes = True
    parser.indent(mapping=2, sequence=4, offset=2)
    parser.width = 100
    return parser


def yaml_path(index: str, year: int) -> Path:
    prof = profile(index)
    return prof["data_dir"] / prof["filename"].format(year=year)


def load_year(index: str, year: int):
    path = yaml_path(index, year)
    if not path.exists():
        return None
    parser = yaml_rt()
    with path.open(encoding="utf-8") as handle:
        return parser.load(handle)


def final_membership(data: dict) -> set[str]:
    members = set(data.get("tickers_on_Jan_1") or [])
    for _, change in sorted((data.get("changes") or {}).items(), key=lambda item: str(item[0])):
        change = change or {}
        members -= set(change.get("difference") or [])
        members |= set(change.get("union") or [])
    return members


def candidate_changes(index: str, threshold: float = 0.90) -> list[dict]:
    prof = profile(index)
    accepted = []
    for row in read_csv(prof["candidate_file"]):
        if row.get("manual_review_required", "").lower() == "true":
            continue
        try:
            confidence = float(row.get("confidence_score", 0))
        except ValueError:
            continue
        if confidence < threshold or not row.get("effective_date"):
            continue
        accepted.append(
            {
                **row,
                "confidence_score": confidence,
                "added": sorted(filter(None, row.get("added_tickers", "").split(";"))),
                "removed": sorted(filter(None, row.get("removed_tickers", "").split(";"))),
            }
        )
    return accepted


def apply_candidates(
    index: str,
    apply: bool = False,
    correction_mode: bool = False,
    threshold: float = 0.90,
) -> list[dict]:
    changes = candidate_changes(index, threshold)
    actions: list[dict] = []
    today = date.today()
    parser = yaml_rt()
    touched: dict[int, object] = {}

    for candidate in changes:
        effective = date.fromisoformat(candidate["effective_date"])
        if effective.year < today.year and not correction_mode:
            actions.append({**candidate, "status": "manual_review", "reason": "historical correction flag required"})
            continue
        data = touched.get(effective.year) or load_year(index, effective.year)
        if data is None:
            previous = load_year(index, effective.year - 1)
            if previous is None:
                actions.append({**candidate, "status": "manual_review", "reason": "previous-year anchor missing"})
                continue
            data = {
                "year": effective.year,
                "tickers_on_Jan_1": sorted(final_membership(previous)),
                "changes": {},
            }
        touched[effective.year] = data
        date_key = candidate["effective_date"]
        entries = data.setdefault("changes", {})
        existing = entries.get(date_key)
        desired_removed = candidate["removed"]
        desired_added = candidate["added"]
        if existing:
            old_removed = sorted(existing.get("difference") or [])
            old_added = sorted(existing.get("union") or [])
            if old_removed != desired_removed or old_added != desired_added:
                actions.append({**candidate, "status": "manual_review", "reason": "contradicts existing same-day change"})
                continue
            status = "source_metadata_added" if not existing.get("source_url") else "already_present"
            if not existing.get("source_url"):
                existing["source_url"] = candidate["source_url"]
                existing["source_title"] = candidate["source_title"]
                existing["announcement_date"] = candidate["announcement_date"]
                existing["confidence_score"] = candidate["confidence_score"]
            actions.append({**candidate, "status": status, "reason": "membership already matches"})
            continue

        current = set(data.get("tickers_on_Jan_1") or [])
        for key, entry in sorted(entries.items(), key=lambda item: str(item[0])):
            if str(key) >= date_key:
                break
            current -= set(entry.get("difference") or [])
            current |= set(entry.get("union") or [])
        invalid_remove = sorted(set(desired_removed) - current)
        duplicate_add = sorted(set(desired_added) & current)
        if invalid_remove or duplicate_add:
            reason = f"state conflict remove_missing={invalid_remove} add_existing={duplicate_add}"
            actions.append({**candidate, "status": "manual_review", "reason": reason})
            continue
        entry = {}
        if desired_removed:
            entry["difference"] = desired_removed
        if desired_added:
            entry["union"] = desired_added
        entry["source_url"] = candidate["source_url"]
        entry["source_title"] = candidate["source_title"]
        entry["announcement_date"] = candidate["announcement_date"]
        entry["confidence_score"] = candidate["confidence_score"]
        if effective > today:
            entry["pending"] = True
        entries[date_key] = entry
        actions.append({**candidate, "status": "add", "reason": "validated official change"})

    if apply:
        for year, data in touched.items():
            ordered = dict(sorted((data.get("changes") or {}).items(), key=lambda item: str(item[0])))
            data["changes"] = ordered
            path = yaml_path(index, year)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as handle:
                parser.dump(data, handle)

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIT_DIR / f"{index}_update_plan.json").write_text(
        json.dumps(actions, indent=2, default=str) + "\n", encoding="utf-8"
    )
    if correction_mode:
        lines = ["# Membership Correction Report", "", f"Generated: {iso_now()}", ""]
        lines.extend(
            f"- {item['effective_date']}: {item['status']} - {item['reason']}"
            for item in actions
        )
        (AUDIT_DIR / "correction_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return actions


def validate_dataset(index: str) -> tuple[list[str], list[str], dict]:
    prof = profile(index)
    errors: list[str] = []
    warnings: list[str] = []
    loaded: dict[int, dict] = {}
    paths = sorted(prof["data_dir"].glob(prof["glob"]))
    mapping = load_ticker_mapping()

    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            year = data.get("year")
            if not isinstance(year, int):
                errors.append(f"{path.name}: year must be an integer")
                continue
            loaded[year] = data
            members = data.get("tickers_on_Jan_1")
            if not isinstance(members, list) or not members:
                errors.append(f"{path.name}: tickers_on_Jan_1 must be a non-empty list")
                continue
            if len(members) != len(set(members)):
                errors.append(f"{path.name}: duplicate Jan 1 tickers")
            if any(not str(ticker).strip() for ticker in members):
                errors.append(f"{path.name}: blank Jan 1 ticker")
            if not prof["min_members"] <= len(members) <= prof["max_members"]:
                errors.append(f"{path.name}: unreasonable Jan 1 count {len(members)}")

            current = set(members)
            for raw_date, entry in sorted((data.get("changes") or {}).items(), key=lambda item: str(item[0])):
                effective = date.fromisoformat(str(raw_date))
                entry = entry or {}
                removed = entry.get("difference") or []
                added = entry.get("union") or []
                if not removed and not added:
                    errors.append(f"{path.name} {effective}: empty change")
                if len(removed) != len(set(removed)) or len(added) != len(set(added)):
                    errors.append(f"{path.name} {effective}: duplicate ticker in change")
                overlap = sorted(set(removed) & set(added))
                if overlap:
                    errors.append(f"{path.name} {effective}: same ticker added and removed {overlap}")
                if effective > date.today() and not entry.get("pending", False):
                    errors.append(f"{path.name} {effective}: future change is not marked pending")
                missing = sorted(set(removed) - current)
                duplicate = sorted(set(added) & current)
                if missing:
                    errors.append(f"{path.name} {effective}: removes non-members {missing}")
                if duplicate:
                    errors.append(f"{path.name} {effective}: adds existing members {duplicate}")
                for ticker in removed + added:
                    normalized = normalize_ticker(str(ticker), mapping)
                    if normalized is None:
                        errors.append(f"{path.name} {effective}: unknown ticker format {ticker!r}")
                current -= set(removed)
                current |= set(added)
                if entry.get("source_url"):
                    if not official_url(str(entry["source_url"]), prof["official_domains"]):
                        errors.append(f"{path.name} {effective}: source URL is not official")
                else:
                    warnings.append(f"{path.name} {effective}: legacy change has no official source metadata")
        except Exception as exc:
            errors.append(f"{path.name}: {exc}")

    years = sorted(loaded)
    for left, right in zip(years, years[1:]):
        if right != left + 1:
            errors.append(f"missing year between {left} and {right}")
            continue
        expected = final_membership(loaded[left])
        actual = set(loaded[right].get("tickers_on_Jan_1") or [])
        if expected != actual:
            errors.append(
                f"continuity {left}->{right}: missing={sorted(expected-actual)} "
                f"extra={sorted(actual-expected)}"
            )
    summary = {
        "index_name": prof["index_name"],
        "files": len(paths),
        "first_year": years[0] if years else None,
        "last_year": years[-1] if years else None,
        "errors": len(errors),
        "warnings": len(warnings),
        "validated_at": iso_now(),
    }
    return errors, warnings, summary


def write_validation_report(index: str) -> tuple[list[str], list[str], dict]:
    errors, warnings, summary = validate_dataset(index)
    lines = [
        "# Membership Validation Report",
        "",
        f"- Index: {summary['index_name']}",
        f"- Generated: {summary['validated_at']}",
        f"- YAML files: {summary['files']}",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        "",
        "## Errors",
        "",
    ]
    lines.extend(f"- {item}" for item in errors)
    if not errors:
        lines.append("- None")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {item}" for item in warnings)
    if not warnings:
        lines.append("- None")
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIT_DIR / "validation_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return errors, warnings, summary


def build_audit_reports() -> dict:
    all_rows = []
    for key in INDEX_PROFILES:
        path = INDEX_PROFILES[key]["candidate_file"]
        if path.exists():
            all_rows.extend(read_csv(path))
    action_lookup = {}
    for plan_path in AUDIT_DIR.glob("*_update_plan.json"):
        for action in json.loads(plan_path.read_text(encoding="utf-8")):
            lookup_key = (
                action.get("index_name"),
                action.get("effective_date"),
                action.get("source_url"),
            )
            action_lookup[lookup_key] = action

    manual = read_csv(AUDIT_DIR / "manual_review_required.csv")
    manual_keys = {
        (row.get("index_name"), row.get("effective_date"), row.get("source_url"))
        for row in manual
    }
    for row in all_rows:
        lookup_key = (row.get("index_name"), row.get("effective_date"), row.get("source_url"))
        action = action_lookup.get(lookup_key, {})
        if action.get("status") == "manual_review" and lookup_key not in manual_keys:
            manual.append({**row, "review_reason": action.get("reason", "manual review required")})
            manual_keys.add(lookup_key)
    write_csv(AUDIT_DIR / "manual_review_required.csv", manual, MANUAL_FIELDS)

    lines = [
        "# PIT Membership Update Diff",
        "",
        f"Generated: {iso_now()}",
        "",
        "| Index | Effective date | Added | Removed | Confidence | Manual review | Source |",
        "|---|---|---|---|---:|---|---|",
    ]
    for row in all_rows:
        action = action_lookup.get(
            (row.get("index_name"), row.get("effective_date"), row.get("source_url")),
            {},
        )
        requires_review = (
            row.get("manual_review_required", "").lower() == "true"
            or action.get("status") == "manual_review"
        )
        source = f"[{row['source_title']}]({row['source_url']})"
        lines.append(
            f"| {row['index_name']} | {row['effective_date'] or 'unknown'} | "
            f"{row['added_tickers'] or '-'} | {row['removed_tickers'] or '-'} | "
            f"{row['confidence_score']} | {str(requires_review).lower()} | {source} |"
        )
    if not all_rows:
        lines.append("| - | - | - | - | - | - | No candidates fetched |")
    (AUDIT_DIR / "update_diff_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    confidence_lines = [
        "# Source Confidence Report",
        "",
        f"Generated: {iso_now()}",
        "",
        f"- Candidate changes: {len(all_rows)}",
        f"- Manual-review items: {len(manual)}",
        f"- High confidence (>= 0.90): {sum(float(r.get('confidence_score') or 0) >= 0.90 for r in all_rows)}",
        "",
        "Only official domains listed in `metadata/source_registry.yaml` are accepted.",
    ]
    (AUDIT_DIR / "source_confidence_report.md").write_text(
        "\n".join(confidence_lines) + "\n", encoding="utf-8"
    )
    return {"candidates": len(all_rows), "manual_review": len(manual)}


def latest_yaml_change(index: str) -> str:
    prof = profile(index)
    latest = ""
    for path in prof["data_dir"].glob(prof["glob"]):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for value, entry in (data.get("changes") or {}).items():
            effective = date.fromisoformat(str(value))
            if effective > date.today() and (entry or {}).get("pending", False):
                continue
            latest = max(latest, str(value))
    return latest


def check_freshness(index: str) -> dict:
    prof = profile(index)
    fetch_state_path = METADATA_DIR / f"{index}_fetch_state.json"
    fetch_state = json.loads(fetch_state_path.read_text(encoding="utf-8")) if fetch_state_path.exists() else {}
    latest_change = latest_yaml_change(index)
    trusted = date.fromisoformat(latest_change) if latest_change else None
    stale_after = trusted.fromordinal(trusted.toordinal() + 30) if trusted else None
    warnings = []
    if not trusted:
        warnings.append("no dated membership changes found")
    elif date.today() > stale_after:
        warnings.append(f"latest trusted change is more than 30 days old ({latest_change})")
    if not fetch_state.get("successful"):
        warnings.append("no recent successful official-source fetch")
    result = {
        "index_name": prof["index_name"],
        "latest_yaml_year": max(
            [int(path.stem.rsplit("-", 1)[-1]) for path in prof["data_dir"].glob(prof["glob"])],
            default=None,
        ),
        "latest_change_date": latest_change or None,
        "latest_official_source_checked": fetch_state.get("fetched_at"),
        "latest_successful_fetch": fetch_state.get("fetched_at") if fetch_state.get("successful") else None,
        "latest_trusted_date": latest_change or None,
        "stale_after_date": stale_after.isoformat() if stale_after else None,
        "confidence_level": "high" if not warnings else "stale_or_incomplete",
        "warnings": warnings,
    }
    METADATA_DIR.mkdir(parents=True, exist_ok=True)
    (METADATA_DIR / "data_freshness.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    lines = ["# Data Freshness Report", "", f"Generated: {iso_now()}", ""]
    lines.extend(f"- **{key}**: {value}" for key, value in result.items() if key != "warnings")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- None")
    (AUDIT_DIR / "freshness_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result
