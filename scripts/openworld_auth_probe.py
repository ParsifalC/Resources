#!/usr/bin/env python3
"""Read-only authenticated probe for OpenWorld's Create VPS page.

This probe performs exactly one HTTP GET. It never submits forms or creates a VPS.
The session cookie is read from OPENWORLD_SESSIONCOOKIE and is never printed.
The parser emits only sanitized form/select metadata; it never logs hidden input values,
CSRF tokens, cookies, or the full response body.
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
UA = "Mozilla/5.0 (compatible; Resources-OpenWorld-Auth-Probe/1.1; +https://github.com/ParsifalC/Resources)"


class CreatePageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.visible_parts = []
        self.labels = {}
        self._label_for = None
        self._label_parts = []
        self.selects = []
        self._select = None
        self._option = None
        self._option_parts = []
        self.forms = []

    @staticmethod
    def _attrs(attrs):
        return {str(k).lower(): (v if v is not None else "") for k, v in attrs}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        data = self._attrs(attrs)
        if tag in {"script", "style", "noscript", "template"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "label":
            self._label_for = data.get("for") or None
            self._label_parts = []
        elif tag == "form":
            self.forms.append({
                "method": (data.get("method") or "GET").upper(),
                "action": data.get("action") or None,
            })
        elif tag == "select":
            self._select = {
                "id": data.get("id") or None,
                "name": data.get("name") or None,
                "disabled": "disabled" in data,
                "required": "required" in data,
                "options": [],
            }
        elif tag == "option" and self._select is not None:
            self._option = {
                "disabled": "disabled" in data,
                "selected": "selected" in data,
                "value_present": bool(data.get("value")),
                "text": "",
            }
            self._option_parts = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "label" and self._label_for:
            text = " ".join(" ".join(self._label_parts).split())
            if text:
                self.labels[self._label_for] = text[:160]
            self._label_for = None
            self._label_parts = []
        elif tag == "option" and self._option is not None and self._select is not None:
            self._option["text"] = " ".join(" ".join(self._option_parts).split())[:240]
            self._select["options"].append(self._option)
            self._option = None
            self._option_parts = []
        elif tag == "select" and self._select is not None:
            self.selects.append(self._select)
            self._select = None

    def handle_data(self, data):
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if text:
            self.visible_parts.append(text)
            if self._label_for is not None:
                self._label_parts.append(text)
            if self._option is not None:
                self._option_parts.append(text)

    def finalize(self):
        for select in self.selects:
            key = select.get("id") or select.get("name")
            select["label"] = self.labels.get(key) if key else None
        return " ".join(self.visible_parts)


def parse_page(raw_html):
    parser = CreatePageParser()
    parser.feed(raw_html)
    text = parser.finalize()
    return text, parser.selects, parser.forms


def extract_title(raw_html):
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
    if not match:
        return None
    return " ".join(html_module.unescape(re.sub(r"<[^>]+>", " ", match.group(1))).split())[:200]


def classify_auth(final_url, title, text):
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


def _field_identity(select):
    return " ".join(
        str(x or "") for x in (select.get("id"), select.get("name"), select.get("label"))
    ).lower()


def summarize_select(select):
    return {
        "id": select.get("id"),
        "name": select.get("name"),
        "label": select.get("label"),
        "disabled": bool(select.get("disabled")),
        "required": bool(select.get("required")),
        "options": [
            {
                "text": option.get("text"),
                "disabled": bool(option.get("disabled")),
                "selected": bool(option.get("selected")),
                "value_present": bool(option.get("value_present")),
            }
            for option in select.get("options", [])[:50]
        ],
        "option_count": len(select.get("options", [])),
    }


def inspect_inventory(text, selects):
    lower = text.lower()
    out_of_stock_phrases = [
        "no available servers",
        "no servers available",
        "out of stock",
        "no available node",
        "no available nodes",
        "no locations available",
        "no location available",
    ]
    matched_out_of_stock = [phrase for phrase in out_of_stock_phrases if phrase in lower]

    roles = {"plan": [], "location": [], "node": [], "server": []}
    for select in selects:
        ident = _field_identity(select)
        if "plan" in ident:
            roles["plan"].append(select)
        if any(word in ident for word in ("location", "region", "datacenter", "data center")):
            roles["location"].append(select)
        if "node" in ident:
            roles["node"].append(select)
        if "server" in ident:
            roles["server"].append(select)

    plan_options = []
    for select in roles["plan"]:
        plan_options.extend(select.get("options", []))
    free_options = [
        option for option in plan_options
        if re.search(r"\bfree\b", option.get("text", ""), re.I)
    ]
    free_enabled = [option for option in free_options if not option.get("disabled")]

    capacity_selects = roles["node"] + roles["server"] + roles["location"]
    usable_capacity_options = []
    for select in capacity_selects:
        for option in select.get("options", []):
            text_value = (option.get("text") or "").strip()
            placeholder = not text_value or bool(re.search(
                r"^(select|choose|please select|none|n/a|no available|loading)", text_value, re.I
            ))
            if option.get("value_present") and not option.get("disabled") and not placeholder:
                usable_capacity_options.append({
                    "field": select.get("id") or select.get("name") or select.get("label"),
                    "text": text_value,
                })

    evidence = {
        "matched_out_of_stock_phrases": matched_out_of_stock,
        "free_plan_option_count": len(free_options),
        "free_plan_enabled_count": len(free_enabled),
        "usable_capacity_option_count": len(usable_capacity_options),
        "usable_capacity_options": usable_capacity_options[:30],
        "role_select_counts": {key: len(value) for key, value in roles.items()},
        "relevant_selects": {
            key: [summarize_select(select) for select in value]
            for key, value in roles.items()
        },
    }

    # Conservative classification. Presence of a Free plan alone is not stock.
    # We only call AVAILABLE when the page exposes an enabled Free option and at
    # least one usable location/node/server option in the same server-rendered GET.
    if matched_out_of_stock and free_options:
        return "OUT_OF_STOCK", "Free plan is present and the page explicitly reports no available capacity", evidence
    if free_enabled and usable_capacity_options:
        return "AVAILABLE", "enabled Free plan and usable location/node/server options are present in the GET response", evidence
    if free_options and not usable_capacity_options:
        return "OUT_OF_STOCK", "Free plan is present but no usable location/node/server option is exposed", evidence
    if not free_options:
        return "UNKNOWN", "could not identify a Free plan option confidently", evidence
    return "UNKNOWN", "page structure was parsed but did not provide enough evidence for stock status", evidence


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
        "inventory_state": "UNKNOWN",
        "reason": None,
        "inventory_reason": None,
        "diagnostics": {},
        "inventory": {},
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
    text, selects, forms = parse_page(raw_html)
    title = extract_title(raw_html)
    auth_state, reason, markers = classify_auth(final_url, title, text)
    inventory_state, inventory_reason, inventory = inspect_inventory(text, selects)
    if auth_state != "AUTHENTICATED":
        inventory_state = "UNKNOWN"
        inventory_reason = "inventory was not trusted because authentication was not confirmed"

    result.update(
        {
            "auth_state": auth_state,
            "inventory_state": inventory_state,
            "reason": reason,
            "inventory_reason": inventory_reason,
            "inventory": inventory,
            "diagnostics": {
                "http_status": status,
                "final_url": final_url,
                "content_type": content_type,
                "content_length": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "title": title,
                "visible_text_length": len(text),
                "select_count": len(selects),
                "forms": forms[:10],
                "markers": markers,
            },
        }
    )

    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    safe_diag = result["diagnostics"].copy()
    safe_diag["markers"] = markers
    print(f"Authenticated probe: state={auth_state} reason={reason}")
    print("Authenticated probe diagnostics:", json.dumps(safe_diag, ensure_ascii=False, sort_keys=True))
    print(f"Inventory probe: state={inventory_state} reason={inventory_reason}")
    print("Inventory evidence:", json.dumps(inventory, ensure_ascii=False, sort_keys=True))

    if auth_state == "AUTHENTICATED":
        raise SystemExit(0)
    if auth_state == "UNAUTHENTICATED":
        raise SystemExit(2)
    raise SystemExit(3)


if __name__ == "__main__":
    main()
