#!/usr/bin/env python3
"""Read-only authenticated probe for OpenWorld's Create VPS page.

This probe performs exactly one HTTP GET. It never submits forms or creates a VPS.
The session cookie is read from OPENWORLD_SESSIONCOOKIE and is never printed.
"""

import hashlib
import html as html_module
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

URL = "https://openworld.eu.org/createvps"
UA = "Mozilla/5.0 (compatible; Resources-OpenWorld-Auth-Probe/1.0; +https://github.com/ParsifalC/Resources)"


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._ignored_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if not self._ignored_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def visible_text(raw_html):
    parser = VisibleTextParser()
    parser.feed(raw_html)
    return " ".join(parser.parts)


def extract_title(raw_html):
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
    if not match:
        return None
    return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())[:200]


def classify(final_url, title, text):
    lower = text.lower()
    parsed = urllib.parse.urlparse(final_url)

    create_markers = {
        "create_vps": "create vps" in lower,
        "plan": bool(re.search(r"\bplan\b", lower)),
        "location": bool(re.search(r"\blocation\b", lower)),
        "hostname": bool(re.search(r"\bhostname\b", lower)),
        "operating_system": "operating system" in lower or bool(re.search(r"\bos\b", lower)),
    }
    login_markers = {
        "sign_in": "sign in" in lower or "signin" in lower,
        "log_in": "log in" in lower or "login" in lower,
        "clerk": "clerk" in lower,
    }

    on_create_path = parsed.path.rstrip("/") == "/createvps"
    create_score = sum(create_markers.values())
    login_score = sum(login_markers.values())

    if on_create_path and create_markers["create_vps"] and create_score >= 2 and login_score == 0:
        state = "AUTHENTICATED"
        reason = "remained on /createvps and authenticated create-page markers were present"
    elif not on_create_path or login_score >= 2:
        state = "UNAUTHENTICATED"
        reason = "request left /createvps or login markers were detected"
    else:
        state = "UNKNOWN"
        reason = "response did not match the authenticated or unauthenticated signatures confidently"

    return state, reason, {
        "on_create_path": on_create_path,
        "create_markers": create_markers,
        "login_markers": login_markers,
        "create_score": create_score,
        "login_score": login_score,
        "title_mentions_create": bool(title and "create" in title.lower()),
    }


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "auth_probe.json")
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    cookie = os.environ.get("OPENWORLD_SESSIONCOOKIE", "").strip()

    result = {
        "checked_at": checked_at,
        "source": URL,
        "method": "GET",
        "read_only": True,
        "cookie_scope": "sessioncookie-only",
        "auth_state": "UNKNOWN",
        "reason": None,
        "diagnostics": {},
        "errors": [],
    }

    if not cookie:
        result["reason"] = "OPENWORLD_SESSIONCOOKIE is missing or empty"
        result["errors"].append("missing OPENWORLD_SESSIONCOOKIE")
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Authenticated probe: state=UNKNOWN reason=missing secret")
        raise SystemExit(3)

    request = urllib.request.Request(
        URL,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://openworld.eu.org/dashboard",
            "Cookie": f"sessioncookie={cookie}",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            final_url = response.geturl()
            status = response.getcode()
            content_type = response.headers.get("Content-Type")
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp else b""
        final_url = exc.geturl() or URL
        status = exc.code
        content_type = exc.headers.get("Content-Type") if exc.headers else None
        result["errors"].append(f"HTTPError: {exc.code} {exc.reason}")
    except Exception as exc:
        result["reason"] = f"request failed: {type(exc).__name__}: {exc}"
        result["errors"].append(result["reason"])
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Authenticated probe: state=UNKNOWN error={type(exc).__name__}")
        raise SystemExit(3)

    raw_html = body.decode("utf-8", errors="replace")
    text = visible_text(raw_html)
    title = extract_title(raw_html)
    state, reason, markers = classify(final_url, title, text)

    result.update(
        {
            "auth_state": state,
            "reason": reason,
            "diagnostics": {
                "http_status": status,
                "final_url": final_url,
                "content_type": content_type,
                "content_length": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "title": title,
                "visible_text_length": len(text),
                "markers": markers,
            },
        }
    )

    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    safe_diag = result["diagnostics"].copy()
    safe_diag["markers"] = markers
    print(f"Authenticated probe: state={state} reason={reason}")
    print("Authenticated probe diagnostics:", json.dumps(safe_diag, ensure_ascii=False, sort_keys=True))

    if state == "AUTHENTICATED":
        raise SystemExit(0)
    if state == "UNAUTHENTICATED":
        raise SystemExit(2)
    raise SystemExit(3)


if __name__ == "__main__":
    main()
