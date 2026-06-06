#!/usr/bin/env python3
"""Parse one saved official announcement for troubleshooting/manual review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from refresh_lib import parse_announcement, text_from_content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", required=True, choices=("nq100", "sp500"))
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-title", required=True)
    args = parser.parse_args()

    content = args.file.read_bytes()
    content_type = "application/pdf" if args.file.suffix.lower() == ".pdf" else "text/html"
    text, _ = text_from_content(content, content_type, args.file)
    changes = parse_announcement(
        args.index, content, text, args.source_url, args.source_title
    )
    print(json.dumps([change.__dict__ for change in changes], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
