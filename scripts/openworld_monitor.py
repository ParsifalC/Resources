#!/usr/bin/env python3
"""Read-only anonymous monitor for OpenWorld public capacity counters."""

import argparse
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://openworld.eu.org/"
UA = "Mozilla/5.0 (compatible; Resources-OpenWorld-Monitor/1.0; +https://github.com/ParsifalC/Resources)"


def fetch_html():
    req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_counter(html, label):
    # The public homepage renders counters near their labels. Support both
    # number-before-label and label-before-number layouts without relying on
    # fragile CSS classes.
    patterns = [
        rf"([0-9][0-9,]*)\s*</[^>]+>\s*(?:<[^>]+>\s*){{0,4}}{re.escape(label)}\b",
        rf"{re.escape(label)}\b(?:\s*</[^>]+>\s*|\s*<[^>]+>\s*){{0,6}}([0-9][0-9,]*)",
        rf"([0-9][0-9,]*)\s+{re.escape(label)}\b",
        rf"{re.escape(label)}\s+([0-9][0-9,]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I | re.S)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


def load_previous(path):
    if not path or not Path(path).is_file() or Path(path).stat().st_size == 0:
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous")
    parser.add_argument("--output", required=True)
    parser.add_argument("--diff-output", required=True)
    args = parser.parse_args()

    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    errors = []
    counters = {}
    try:
        html = fetch_html()
        for key, label in (("nodes", "Nodes"), ("vps", "VPS"), ("ips", "IPs"), ("users", "Users")):
            value = extract_counter(html, label)
            if value is not None:
                counters[key] = value
        # VPS and Nodes are the core capacity signals. If either disappears,
        # treat the probe as invalid rather than persisting a misleading state.
        missing = [key for key in ("nodes", "vps") if key not in counters]
        if missing:
            errors.append("missing public counters: " + ", ".join(missing))
    except Exception as exc:
        errors.append(f"fetch failed: {type(exc).__name__}: {exc}")

    current = {
        "checked_at": checked_at,
        "source": URL,
        "anonymous": True,
        "read_only": True,
        "counters": counters,
        "errors": errors,
    }
    previous = load_previous(args.previous)
    initialized = not bool(previous and not previous.get("errors"))
    changes = {}
    if not errors and not initialized:
        old = previous.get("counters") or {}
        for key in sorted(set(old) | set(counters)):
            before, after = old.get(key), counters.get(key)
            if before != after:
                changes[key] = {
                    "before": before,
                    "after": after,
                    "delta": after - before if isinstance(before, int) and isinstance(after, int) else None,
                }

    diff = {
        "initialized": initialized,
        "changed": bool(changes),
        "counters": changes,
    }
    Path(args.output).write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.diff_output).write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if errors:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
