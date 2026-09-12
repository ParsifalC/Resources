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
DATA_CENTER_URL = "https://hax.co.id/data-center"
USER_AGENT = "Mozilla/5.0 (compatible; HaxInventoryMonitor/1.0; +https://github.com/ParsifalC/Resources)"
DATACENTER_RE = re.compile(r"\b(?:EU-\d+|US-OpenVZ-\d+)\b", re.I)


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


class PageStructureParser(HTMLParser):
    """Collect human-visible structure while ignoring script/style noise."""

    IGNORED_TAGS = {"script", "style", "noscript", "template"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored_depth = 0
        self.parts: list[str] = []
        self.headings: list[str] = []
        self.heading_parts: list[str] | None = None
        self.in_row = False
        self.row: list[str] = []
        self.cell_parts: list[str] | None = None
        self.table_rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            self.ignored_depth += 1
            return
        if self.ignored_depth:
            return
        if tag in self.HEADING_TAGS:
            self.heading_parts = []
        elif tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in {"th", "td"}:
            self.cell_parts = []

    def handle_data(self, data: str) -> None:
        if self.ignored_depth:
            return
        text = " ".join(data.split()).strip()
        if not text:
            return
        self.parts.append(text)
        if self.heading_parts is not None:
            self.heading_parts.append(text)
        if self.cell_parts is not None:
            self.cell_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.IGNORED_TAGS:
            if self.ignored_depth:
                self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag in self.HEADING_TAGS and self.heading_parts is not None:
            text = " ".join(self.heading_parts).strip()
            if text:
                self.headings.append(text)
            self.heading_parts = None
        elif self.in_row and tag in {"th", "td"} and self.cell_parts is not None:
            text = " ".join(self.cell_parts).strip()
            if text:
                self.row.append(text)
            self.cell_parts = None
        elif tag == "tr" and self.in_row:
            if self.row:
                self.table_rows.append(self.row)
            self.in_row = False
            self.row = []
            self.cell_parts = None


def make_request(url: str) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
        },
    )


def fetch(url: str, timeout: int = 20) -> str:
    with urllib.request.urlopen(make_request(url), timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def datacenter_contexts(parts: list[str], names: list[str]) -> dict[str, list[str]]:
    contexts: dict[str, list[str]] = {}
    for name in names:
        needle = name.lower()
        seen: set[str] = set()
        matches: list[str] = []
        for index, part in enumerate(parts):
            if needle not in part.lower():
                continue
            start = max(0, index - 4)
            end = min(len(parts), index + 9)
            context = " | ".join(parts[start:end])[:1600]
            if context and context not in seen:
                seen.add(context)
                matches.append(context)
            if len(matches) >= 4:
                break
        contexts[name] = matches
    return contexts


def parse_data_center_stats(parts: list[str]) -> dict[str, Any]:
    text = "\n".join(parts)
    counts: dict[str, int] = {}
    pattern = re.compile(r"(?:\./)?((?:EU-\d+)|(?:US-OpenVZ-\d+))\s*\n\s*(\d+)\s*VPS\b", re.I)
    for name, count in pattern.findall(text):
        counts[name] = int(count)

    total_match = re.search(r"Number of VPS Online\s*\n\s*(\d+)\s*VPS\b", text, re.I)
    online_total = int(total_match.group(1)) if total_match else None
    sum_servers = sum(counts.values()) if counts else None
    consistent = (
        online_total == sum_servers
        if isinstance(online_total, int) and isinstance(sum_servers, int)
        else None
    )
    return {
        "servers": dict(sorted(counts.items())),
        "online_total": online_total,
        "sum_servers": sum_servers,
        "consistent": consistent,
    }


def diagnose_data_center(url: str, timeout: int = 20) -> dict[str, Any]:
    result: dict[str, Any] = {
        "url": url,
        "reachable": False,
        "status": None,
        "final_url": None,
        "content_type": None,
        "content_length": None,
        "title": None,
        "page_kind": "unknown",
        "challenge_detected": False,
        "challenge_markers": [],
        "stats": {"servers": {}, "online_total": None, "sum_servers": None, "consistent": None},
        "datacenter_tokens": [],
        "headings": [],
        "table_rows": [],
        "datacenter_contexts": {},
        "text_excerpt": None,
        "error": None,
    }
    try:
        with urllib.request.urlopen(make_request(url), timeout=timeout) as response:
            body = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            html = body.decode(charset, errors="replace")
            result["reachable"] = True
            result["status"] = getattr(response, "status", response.getcode())
            result["final_url"] = response.geturl()
            result["content_type"] = response.headers.get("Content-Type")
            result["content_length"] = len(body)

            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            if title_match:
                result["title"] = " ".join(re.sub(r"<[^>]+>", " ", title_match.group(1)).split())[:200]

            parser = PageStructureParser()
            parser.feed(html)
            visible_text = "\n".join(parser.parts)
            visible_lower = visible_text.lower()
            tokens = sorted({match.group(0) for match in DATACENTER_RE.finditer(visible_text)}, key=str.lower)
            stats = parse_data_center_stats(parser.parts)
            result["stats"] = stats
            result["datacenter_tokens"] = tokens[:50]
            result["headings"] = parser.headings[:30]
            result["table_rows"] = parser.table_rows[:30]
            result["datacenter_contexts"] = datacenter_contexts(parser.parts, tokens)

            lower = html.lower()
            marker_patterns = {
                "verification_text": "please wait while your request is being verified",
                "cloudflare_challenge_id": "cf-chl-",
                "cloudflare_challenge_path": "/cdn-cgi/challenge-platform/",
                "turnstile": "cf-turnstile",
                "challenge_form": "challenge-form",
            }
            markers = [name for name, marker in marker_patterns.items() if marker in lower]
            title = (result.get("title") or "").strip().lower()
            if title.startswith("just a moment") or title.startswith("one moment"):
                markers.append("challenge_title")
            result["challenge_markers"] = markers

            normal_content = (
                ("hax's data center" in title or "hax data center" in title)
                and "server statistics" in visible_lower
                and bool(stats["servers"])
            )
            hard_challenge = "verification_text" in markers or "challenge_title" in markers
            result["challenge_detected"] = hard_challenge or (bool(markers) and not normal_content)

            excerpt = " | ".join(parser.parts[:100])
            result["text_excerpt"] = excerpt[:3000] if excerpt else None

            if normal_content:
                result["page_kind"] = "hax_data_center"
            elif result["challenge_detected"]:
                result["page_kind"] = "challenge"
            elif tokens:
                result["page_kind"] = "datacenter_content"
    except Exception as exc:  # diagnostic only; never invalidate create-vps/server probes
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


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
        "data_center_stats": {"servers": {}, "online_total": None},
        "release_candidates": [],
    }


def count_changes(before_counts: dict[str, Any], after_counts: dict[str, Any]) -> dict[str, dict[str, int | None]]:
    changes: dict[str, dict[str, int | None]] = {}
    for name in sorted(set(before_counts) | set(after_counts)):
        before = before_counts.get(name)
        after = after_counts.get(name)
        if before != after:
            delta = after - before if isinstance(before, int) and isinstance(after, int) else None
            changes[name] = {"before": before, "after": after, "delta": delta}
    return changes


def make_diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if previous is None:
        return empty_diff(previous)

    prev_dc = set(previous.get("datacenters") or [])
    curr_dc = set(current.get("datacenters") or [])
    dc_added = sorted(curr_dc - prev_dc)
    dc_removed = sorted(prev_dc - curr_dc)

    server_changes = count_changes(previous.get("servers") or {}, current.get("servers") or {})

    previous_stats = previous.get("data_center_stats") or {}
    current_stats = current.get("data_center_stats") or {}
    stats_changes: dict[str, dict[str, int | None]] = {}
    release_candidates: list[dict[str, Any]] = []

    if current.get("data_center_stats_fresh") and previous_stats.get("servers"):
        stats_changes = count_changes(previous_stats.get("servers") or {}, current_stats.get("servers") or {})
        for name, change in stats_changes.items():
            delta = change.get("delta")
            if isinstance(delta, int) and delta < 0:
                release_candidates.append(
                    {
                        "datacenter": name,
                        "before": change.get("before"),
                        "after": change.get("after"),
                        "released": -delta,
                        "source": "data-center",
                    }
                )

    # /server only covers part of Hax. Use a negative change as a fallback release
    # hint only when the richer /data-center snapshot is not fresh.
    if not current.get("data_center_stats_fresh"):
        for name, change in server_changes.items():
            delta = change.get("delta")
            if isinstance(delta, int) and delta < 0:
                release_candidates.append(
                    {
                        "datacenter": name,
                        "before": change.get("before"),
                        "after": change.get("after"),
                        "released": -delta,
                        "source": "server-fallback",
                    }
                )

    prev_online = previous_stats.get("online_total")
    curr_online = current_stats.get("online_total")
    online_change = None
    if current.get("data_center_stats_fresh") and isinstance(prev_online, int) and isinstance(curr_online, int):
        if prev_online != curr_online:
            online_change = {"before": prev_online, "after": curr_online, "delta": curr_online - prev_online}

    # A persistent Create VPS option is not treated as stock: Hax can keep an
    # OpenVZ option visible even when creating it yields an unusable/dead VPS.
    # Alert-worthy signals are a newly appearing option or a drop in the live
    # VPS population, which is only a release candidate, not confirmed stock.
    changed = bool(dc_added or dc_removed or release_candidates)
    return {
        "initialized": False,
        "changed": changed,
        "datacenters": {"added": dc_added, "removed": dc_removed},
        "servers": server_changes,
        "data_center_stats": {"servers": stats_changes, "online_total": online_change},
        "release_candidates": release_candidates,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only Hax VPS inventory/server monitor")
    ap.add_argument("--output", type=Path, default=Path("current.json"))
    ap.add_argument("--previous", type=Path)
    ap.add_argument("--diff-output", type=Path, default=Path("diff.json"))
    args = ap.parse_args()

    previous = read_json(args.previous)
    errors: list[str] = []

    try:
        create_html = fetch(CREATE_URL)
        datacenters, dc_source = parse_datacenters(create_html)
        if dc_source == "unavailable":
            errors.append("create-vps: response was reachable but datacenter options could not be parsed")
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

    data_center_probe = diagnose_data_center(DATA_CENTER_URL)
    raw_stats = data_center_probe.get("stats") or {}
    data_center_stats_fresh = bool(
        data_center_probe.get("page_kind") == "hax_data_center"
        and raw_stats.get("servers")
        and isinstance(raw_stats.get("online_total"), int)
        and raw_stats.get("consistent") is True
    )

    if data_center_stats_fresh:
        data_center_stats = raw_stats
    else:
        previous_stats = (previous or {}).get("data_center_stats") or {}
        data_center_stats = previous_stats if previous_stats.get("servers") else raw_stats

    current = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "datacenters": datacenters,
        "datacenter_source": dc_source,
        "datacenter_option_semantics": "form_option_only_not_confirmed_stock",
        "servers": servers,
        "server_total": sum(servers.values()) if servers else None,
        "data_center_stats": data_center_stats,
        "data_center_stats_fresh": data_center_stats_fresh,
        "data_center_probe": data_center_probe,
        "errors": errors,
        "urls": {"create": CREATE_URL, "server": SERVER_URL, "data_center": DATA_CENTER_URL},
    }

    diff = empty_diff(previous) if errors else make_diff(previous, current)

    args.output.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.diff_output.write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"current": current, "diff": diff}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
