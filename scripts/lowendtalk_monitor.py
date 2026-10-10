#!/usr/bin/env python3
"""Read-only, low-frequency LowEndTalk giveaway comment monitor.

One invocation performs one incremental check. It never signs in, submits a
comment, retries a blocked request or attempts to bypass bot protection.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

THREAD_ID = 221872
THREAD_URL = ("https://lowendtalk.com/discussion/221872/"
              "giveaway-by-adminbolt-racknerd-100x-free-vps-for-a-year-20x-"
              "lifetime-licenses-lets-talk")
AUTHOR = "dustinc"
PAGE_RE = re.compile(r"/discussion/221872/(?:[^?#]*?/)?p(\d+)(?:[/?#]|$)", re.I)
PROFILE_RE = re.compile(r"(?:^|/)profile/([^/?#]+)", re.I)
COMMENT_RE = re.compile(r"^Comment_(\d+)$", re.I)
VOID = frozenset("area base br col embed hr img input link meta param source track wbr".split())


class ThreadParser(HTMLParser):
    """Extract comment ids, header authors, text, and pagination links."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.comment = None
        self.comment_level = 0
        self.comments = []
        self.pages = {1}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        if tag == "a":
            match = PAGE_RE.search(a.get("href") or "")
            if match:
                self.pages.add(int(match.group(1)))

        class_names = set((a.get("class") or "").split())
        comment_id = None
        match = COMMENT_RE.match(a.get("id") or "")
        if match:
            comment_id = int(match.group(1))
        elif "Item" in class_names and "Comment" in class_names:
            raw_id = a.get("data-commentid") or a.get("data-comment-id") or ""
            if raw_id.isdecimal():
                comment_id = int(raw_id)

        if self.comment is None and comment_id is not None:
            self.comment = {"id": comment_id, "author": "", "text": ""}
            self.comment_level = len(self.stack) + 1
        if self.comment is not None and tag == "a" and not self._in_message():
            match = PROFILE_RE.search(a.get("href") or "")
            if match and not self.comment["author"]:
                self.comment["author"] = urllib.parse.unquote(match.group(1)).casefold()

        if tag not in VOID:
            self.stack.append((tag, "Message" in class_names or "userContent" in class_names))

    def _in_message(self):
        return any(flag for _, flag in self.stack[self.comment_level:])

    def handle_data(self, value):
        if self.comment is not None and self._in_message():
            self.comment["text"] += value

    def handle_endtag(self, tag):
        tag = tag.lower()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if self.comment is not None and len(self.stack) < self.comment_level:
            self.comment["text"] = " ".join(self.comment["text"].split())
            self.comments.append(self.comment)
            self.comment = None
            self.comment_level = 0


def parse_thread(html: str, *, page: int) -> ThreadParser:
    parser = ThreadParser()
    parser.pages.add(page)
    parser.feed(html)
    parser.close()
    if not parser.comments or not any(row["author"] for row in parser.comments):
        raise ValueError("No identifiable comments found (login/challenge/layout changed?)")
    if len(parser.comments) >= 25 and max(parser.pages) == 1 and page == 1:
        raise ValueError("Pagination unavailable on busy first page; refusing incomplete baseline")
    return parser


def fetch_page(page: int) -> ThreadParser:
    url = THREAD_URL if page == 1 else f"{THREAD_URL}/p{page}"
    request = urllib.request.Request(url, headers={
        "User-Agent": "ResourcesGiveawayMonitor/1.0 (+https://github.com/ParsifalC/Resources)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type.lower():
                raise ValueError(f"Unexpected content type: {content_type}")
            data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("Page exceeds 2 MB size limit")
            charset = response.headers.get_content_charset() or "utf-8"
            html = data.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}; no immediate retry (respect site restrictions)") from exc
    return parse_thread(html, page=page)


def load_previous(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("State must be an object")
    return value


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def check(previous: dict, fetch=fetch_page) -> tuple[dict, dict]:
    initial = "last_page" not in previous
    last_page = max(1, int(previous.get("last_page") or 1))
    if initial:
        first = fetch(1)
        last_page = max(first.pages)
        parser = first if last_page == 1 else fetch(last_page)
        scanned = [parser]
    else:
        parser = fetch(last_page)
        scanned = [parser]
        target = max(parser.pages)
        if target - last_page > 5:
            raise ValueError("Too many unscanned pages; preserve checkpoint for manual review")
        for page in range(last_page + 1, target + 1):
            scanned.append(fetch(page))
        last_page = max(last_page, target)

    rows = {row["id"]: row for parsed in scanned for row in parsed.comments}
    if not rows:
        raise ValueError("No comments; refusing to overwrite cursor")
    observed_id = max(rows)
    previous_id = int(previous.get("last_comment_id") or 0)
    if not initial and observed_id < previous_id and last_page <= int(previous["last_page"]):
        raise ValueError("Latest comment id regressed; previous state preserved")

    events = []
    if not initial:
        for item in sorted(rows.values(), key=lambda row: row["id"]):
            if item["id"] > previous_id and item["author"] == AUTHOR:
                events.append({
                    "id": item["id"],
                    "author": item["author"],
                    "text": item["text"][:2500],
                    "url": f"https://lowendtalk.com/discussion/comment/{item['id']}/#Comment_{item['id']}",
                })
    snapshot = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "last_page": last_page,
        "last_comment_id": max(previous_id, observed_id),
        "thread_id": THREAD_ID,
    }
    return snapshot, {"initialized": initial, "events": events, "scanned_pages": len(scanned)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--events", type=Path, required=True)
    args = ap.parse_args()
    try:
        snapshot, events = check(load_previous(args.previous))
        write_json(args.output, snapshot)
        write_json(args.events, events)
        print(f"LET: page={snapshot['last_page']} cursor={snapshot['last_comment_id']} "
              f"events={len(events['events'])} initialized={events['initialized']}")
        return 0
    except Exception as exc:
        print(f"LET monitor failed safely: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
