#!/usr/bin/env python3
"""Read-only authenticated OpenWorld Free VPS inventory probe.

Performs exactly one GET to /createvps using OPENWORLD_SESSIONCOOKIE.
It never submits the create form. Inventory is derived from the structured
JSON embedded in each plan-card button's data-plan attribute.
"""

import argparse
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
UA = "Mozilla/5.0 (compatible; Resources-OpenWorld-Inventory-Probe/2.0; +https://github.com/ParsifalC/Resources)"


class CreatePageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.visible_parts = []
        self.plan_cards = []

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
        if tag == "button" and "plan-card-btn" in (data.get("class") or "").split():
            raw_plan = data.get("data-plan")
            if raw_plan:
                try:
                    plan = json.loads(raw_plan)
                    self.plan_cards.append({
                        "disabled": "disabled" in data,
                        "plan": plan,
                    })
                except json.JSONDecodeError:
                    self.plan_cards.append({
                        "disabled": "disabled" in data,
                        "parse_error": "invalid data-plan JSON",
                    })

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data):
        if self._ignored_depth:
            return
        text = " ".join(data.split())
        if text:
            self.visible_parts.append(text)

    @property
    def visible_text(self):
        return " ".join(self.visible_parts)


def parse_page(raw_html):
    parser = CreatePageParser()
    parser.feed(raw_html)
    return parser.visible_text, parser.plan_cards


def extract_title(raw_html):
    match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.I | re.S)
    if not match:
        return None
    title = html_module.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))
    return " ".join(title.split())[:200]


def classify_auth(final_url, title, text):
    lower = text.lower()
    parsed = urllib.parse.urlparse(final_url)
    on_create_path = parsed.path.rstrip("/") == "/createvps"
    create_markers = {
        "deploy_vps": "deploy a vps" in lower,
        "available_plans": "available plans" in lower,
        "create_vps": "create vps" in lower,
        "plan": bool(re.search(r"\bplan\b", lower)),
        "location": bool(re.search(r"\blocation\b", lower)),
    }
    login_markers = {
        "sign_in": "sign in" in lower or "signin" in lower,
        "log_in": "log in" in lower or "login" in lower,
        "clerk": "clerk" in lower,
    }
    create_score = sum(create_markers.values())
    login_score = sum(login_markers.values())
    if on_create_path and create_score >= 2 and login_score == 0:
        return "AUTHENTICATED", "authenticated Create VPS page detected", {
            "on_create_path": True,
            "create_markers": create_markers,
            "login_markers": login_markers,
        }
    if not on_create_path or login_score >= 2:
        return "UNAUTHENTICATED", "request left /createvps or login markers were detected", {
            "on_create_path": on_create_path,
            "create_markers": create_markers,
            "login_markers": login_markers,
        }
    return "UNKNOWN", "Create VPS authentication signature was inconclusive", {
        "on_create_path": on_create_path,
        "create_markers": create_markers,
        "login_markers": login_markers,
    }


def sanitize_location(loc):
    return {
        "name": loc.get("name"),
        "code": loc.get("code"),
        "available": bool(loc.get("available")),
        "status_text": loc.get("status_text"),
        "vps_count": loc.get("vps_count"),
    }


def sanitize_plan_card(card):
    plan = card.get("plan") or {}
    locations = [sanitize_location(x) for x in (plan.get("locations") or []) if isinstance(x, dict)]
    return {
        "name": plan.get("name"),
        "price": plan.get("price"),
        "stock": plan.get("stock"),
        "active": bool(plan.get("active")),
        "node_type": plan.get("node_type"),
        "cpu": plan.get("cpu"),
        "ram": plan.get("ram"),
        "disk": plan.get("disk"),
        "netmbps": plan.get("netmbps"),
        "bandwidth_gb": plan.get("bandwidth_gb"),
        "button_disabled": bool(card.get("disabled")),
        "locations": locations,
    }


def inspect_inventory(plan_cards):
    parsed_cards = [card for card in plan_cards if isinstance(card.get("plan"), dict)]
    plans = [sanitize_plan_card(card) for card in parsed_cards]
    free_cards = []
    for card in parsed_cards:
        plan = card["plan"]
        name = str(plan.get("name") or "")
        try:
            price = float(plan.get("price"))
        except (TypeError, ValueError):
            price = None
        if re.search(r"\bfree\b", name, re.I) or price == 0:
            free_cards.append(card)

    evidence = {
        "plan_card_count": len(plan_cards),
        "parsed_plan_count": len(parsed_cards),
        "free_plan_count": len(free_cards),
        "plans": plans,
        "free_plans": [sanitize_plan_card(card) for card in free_cards],
    }
    if not free_cards:
        return "UNKNOWN", "no Free plan card was found in structured data-plan JSON", evidence

    valid_stocks = []
    contradictory = False
    any_active = False
    all_disabled = True
    for card in free_cards:
        plan = card["plan"]
        any_active = any_active or bool(plan.get("active"))
        all_disabled = all_disabled and bool(card.get("disabled"))
        try:
            stock = int(plan.get("stock"))
        except (TypeError, ValueError):
            continue
        valid_stocks.append(stock)
        if stock > 0 and card.get("disabled"):
            contradictory = True
        if stock <= 0 and not card.get("disabled"):
            contradictory = True

    evidence["free_stock_total"] = sum(valid_stocks) if valid_stocks else None
    evidence["free_button_all_disabled"] = all_disabled
    evidence["free_any_active"] = any_active

    if contradictory:
        return "UNKNOWN", "Free plan stock and button enabled/disabled state contradict each other", evidence
    if not valid_stocks:
        return "UNKNOWN", "Free plan was found but did not expose numeric stock", evidence
    if any(stock > 0 for stock in valid_stocks) and any_active and not all_disabled:
        return "AVAILABLE", "Free plan reports positive stock and its deploy card is enabled", evidence
    if all(stock <= 0 for stock in valid_stocks):
        return "OUT_OF_STOCK", "Free plan explicitly reports zero stock", evidence
    return "UNKNOWN", "Free plan structured inventory could not be classified confidently", evidence


def write_result(path, result):
    Path(path).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output", nargs="?", default="auth_probe.json")
    ap.add_argument("--html-output")
    args = ap.parse_args()

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
        write_result(args.output, result)
        print("Authenticated inventory probe: auth=UNKNOWN inventory=UNKNOWN reason=missing secret")
        raise SystemExit(3)

    req = urllib.request.Request(
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
        with urllib.request.urlopen(req, timeout=30) as response:
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
        write_result(args.output, result)
        print(f"Authenticated inventory probe: auth=UNKNOWN inventory=UNKNOWN error={type(exc).__name__}")
        raise SystemExit(3)

    if args.html_output:
        Path(args.html_output).write_bytes(body)

    raw_html = body.decode("utf-8", errors="replace")
    text, plan_cards = parse_page(raw_html)
    title = extract_title(raw_html)
    auth_state, reason, markers = classify_auth(final_url, title, text)
    inventory_state, inventory_reason, inventory = inspect_inventory(plan_cards)
    if auth_state != "AUTHENTICATED":
        inventory_state = "UNKNOWN"
        inventory_reason = "inventory ignored because authentication was not confirmed"

    result.update({
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
            "markers": markers,
        },
    })
    write_result(args.output, result)
    print(f"Authenticated inventory probe: auth={auth_state} inventory={inventory_state}")
    print("Inventory evidence:", json.dumps(inventory, ensure_ascii=False, sort_keys=True))

    if auth_state == "AUTHENTICATED":
        raise SystemExit(0)
    if auth_state == "UNAUTHENTICATED":
        raise SystemExit(2)
    raise SystemExit(3)


if __name__ == "__main__":
    main()
