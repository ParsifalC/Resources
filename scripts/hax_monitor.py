#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

CREATE_URL = "https://hax.co.id/create-vps/"
SERVER_URL = "https://hax.co.id/server"
USER_AGENT = "Mozilla/5.0 (compatible; HaxInventoryMonitor/1.0; +https://github.com/ParsifalC/Resources)"


class DatacenterParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_datacenter = False
        self.in_option = False
        self.option_parts: list[str] = []
        self.options: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag.lower() == "select" and attrs_map.get("id") == "datacenter":
            self.in_datacenter = True
        elif self.in_datacenter and tag.lower() == "option":
            self.in_option = True
            self.option_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_datacenter and self.in_option:
            self.option_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.in_datacenter and self.in_option and tag == "option":
            text = " ".join("".join(self.option_parts).split()).strip()
            if text:
                self.options.append(text)
            self.in_option = False
            self.option_parts = []
        elif self.in_datacenter and tag == "select":
            self.in_datacenter = False


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split()).strip()
        if text:
            self.parts.append(text)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def normalize_datacenters(options: list[str]) -> list[str]:
    placeholders = {"select", "-select-", "--select--", "please select"}
    result: list[str] = []
    for option in options:
        cleaned = " ".join(option.split()).strip()
        if not cleaned or cleaned.lower() in placeholders:
            continue
        if cleaned not in result:
            result.append(cleaned)
    return sorted(result)


def parse_datacenters(html: str) -> tuple[list[str], str]:
    parser = DatacenterParser()
    parser.feed(html)
    if parser.options:
        return normalize_datacenters(parser.options), "dom_select"

    candidates = sorted(set(re.findall(r"\b(?:EU-\d+|US-OpenVZ-\d+|[A-Z]{2,}-[A-Za-z0-9-]+)\b", html)))
    return candidates, "raw_html_fallback" if candidates else "unavailable"


def parse_server_counts(html: str) -> dict[str, int]:
    parser = TextParser()
    parser.feed(html)
    text = parser.text

    patterns = [
        re.compile(r"\b((?:EU-\d+)|(?:US-OpenVZ-\d+))\b\s*[:\-=]?\s*(\d+)\s*VPS\b", re.I),
        re.compile(r"\b((?:EU-\d+)|(?:US-OpenVZ-\d+))\b[^\n\d]{0,40}(\d+)\s*VPS\b", re.I),
    ]

    counts: dict[str, int] = {}
    for pattern in patterns:
        for name, count in pattern.findall(text):
            counts[name] = int(count)
        if counts:
            break
    return dict(sorted(counts.items()))


def read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists() or path.stat().st_size == 0:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def empty_diff(previous: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "initialized": previous is None,
        "changed": False,
        "datacenters": {"added": [], "removed": []},
        "servers": {},
    }


def make_diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        return empty_diff(previous)

    prev_dc = set(previous.get("datacenters") or [])
    curr_dc = set(current.get("datacenters") or [])
    dc_added = sorted(curr_dc - prev_dc)
    dc_removed = sorted(prev_dc - curr_dc)

    prev_servers = previous.get("servers") or {}
    curr_servers = current.get("servers") or {}
    names = sorted(set(prev_servers) | set(curr_servers))
    server_changes: dict[str, dict[str, int | None]] = {}
    for name in names:
        before = prev_servers.get(name)
        after = curr_servers.get(name)
        if before != after:
            delta = after - before if isinstance(before, int) and isinstance(after, int) else None
            server_changes[name] = {"before": before, "after": after, "delta": delta}

    changed = bool(dc_added or dc_removed or server_changes)
    return {
        "initialized": False,
        "changed": changed,
        "datacenters": {"added": dc_added, "removed": dc_removed},
        "servers": server_changes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only Hax VPS inventory/server monitor")
    ap.add_argument("--output", type=Path, default=Path("current.json"))
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--diff-output", type=Path, default=Path("diff.json"))
    args = ap.parse_args()

    errors: list[str] = []
    try:
        create_html = fetch(CREATE_URL)
        datacenters, dc_source = parse_datacenters(create_html)
        if dc_source == "unavailable":
            errors.append("create-vps: response was reachable but datacenter inventory could not be parsed")
    except Exception as exc:  # noqa: BLE001 - monitor should report partial failure
        datacenters, dc_source = [], "error"
        errors.append(f"create-vps: {type(exc).__name__}: {exc}")

    try:
        server_html = fetch(SERVER_URL)
        servers = parse_server_counts(server_html)
        if not servers:
            errors.append("server: response was reachable but VPS counts could not be parsed")
    except Exception as exc:  # noqa: BLE001
        servers = {}
        errors.append(f"server: {type(exc).__name__}: {exc}")

    current = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "datacenters": datacenters,
        "datacenter_source": dc_source,
        "servers": servers,
        "server_total": sum(servers.values()) if servers else None,
        "errors": errors,
        "urls": {"create": CREATE_URL, "server": SERVER_URL},
    }

    previous = read_json(args.previous)
    diff = empty_diff(previous) if errors else make_diff(previous, current)

    args.output.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.diff_output.write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"current": current, "diff": diff}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
