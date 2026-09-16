#!/usr/bin/env python3
"""Read-only anonymous monitor for OpenWorld public capacity counters."""

import argparse
import hashlib
import html as html_lib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://openworld.eu.org/"
UA = "Mozilla/5.0 (compatible; Resources-OpenWorld-Monitor/1.1; +https://github.com/ParsifalC/Resources)"
LABELS = (("nodes", "Nodes"), ("vps", "VPS"), ("ips", "IPs"))
MONITORED_KEYS = tuple(key for key, _ in LABELS)


def fetch_html():
    req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace"), {
            "http_status": response.status,
            "content_type": response.headers.get("Content-Type"),
            "content_length": len(body),
            "final_url": response.geturl(),
            "sha256": hashlib.sha256(body).hexdigest(),
        }


def visible_text(raw_html):
    text = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", raw_html)
    text = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_lib.unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_counter(text, label):
    # Actual public rendering is `Nodes: 3`, `VPS: 146`, etc. Parse the
    # normalized visible text instead of depending on DOM tag boundaries.
    patterns = [
        rf"\b{re.escape(label)}\s*:\s*([0-9][0-9,]*)\b",
        rf"\b{re.escape(label)}\s+([0-9][0-9,]*)\b",
        rf"\b([0-9][0-9,]*)\s+{re.escape(label)}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1).replace(",", "")), pattern
    return None, None


def context_for_label(text, label, radius=90):
    match = re.search(rf"\b{re.escape(label)}\b", text, re.I)
    if not match:
        return None
    start = max(0, match.start() - radius)
    end = min(len(text), match.end() + radius)
    return text[start:end]


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
    errors, counters, matched_patterns, contexts = [], {}, {}, {}
    fetch_meta = {}
    text = ""
    try:
        raw_html, fetch_meta = fetch_html()
        text = visible_text(raw_html)
        fetch_meta["visible_text_length"] = len(text)
        fetch_meta["title"] = (re.search(r"(?is)<title[^>]*>(.*?)</title>", raw_html).group(1).strip()
                               if re.search(r"(?is)<title[^>]*>(.*?)</title>", raw_html) else None)
        for key, label in LABELS:
            value, pattern = extract_counter(text, label)
            contexts[key] = context_for_label(text, label)
            if value is not None:
                counters[key] = value
                matched_patterns[key] = pattern
        missing = [key for key in ("nodes", "vps") if key not in counters]
        if missing:
            errors.append("missing public counters: " + ", ".join(missing))
    except Exception as exc:
        errors.append(f"fetch/parse failed: {type(exc).__name__}: {exc}")

    current = {
        "checked_at": checked_at,
        "source": URL,
        "anonymous": True,
        "read_only": True,
        "status": "UNKNOWN" if errors else "OK",
        "counters": counters,
        "errors": errors,
        "diagnostics": {
            "fetch": fetch_meta,
            "matched_patterns": matched_patterns,
            "label_contexts": contexts,
        },
    }
    previous = load_previous(args.previous)
    initialized = not bool(previous and not previous.get("errors") and previous.get("status", "OK") == "OK")
    changes = {}
    if not errors and not initialized:
        old = previous.get("counters") or {}
        # Compare only counters that are intentionally monitored. This also
        # makes migration from legacy snapshots containing `users` silent.
        for key in MONITORED_KEYS:
            before, after = old.get(key), counters.get(key)
            if before != after:
                changes[key] = {
                    "before": before,
                    "after": after,
                    "delta": after - before if isinstance(before, int) and isinstance(after, int) else None,
                }

    diff = {"initialized": initialized, "changed": bool(changes), "counters": changes}
    Path(args.output).write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.diff_output).write_text(json.dumps(diff, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Deliberately emit enough non-sensitive diagnostics into Actions logs for
    # remote troubleshooting. Never dump the whole response body.
    print(f"OpenWorld probe: status={current['status']} checked_at={checked_at}")
    print("Fetch diagnostics:", json.dumps(fetch_meta, ensure_ascii=False, sort_keys=True))
    print("Parsed counters:", json.dumps(counters, ensure_ascii=False, sort_keys=True))
    print("Matched patterns:", json.dumps(matched_patterns, ensure_ascii=False, sort_keys=True))
    if errors:
        print("Errors:", json.dumps(errors, ensure_ascii=False), file=sys.stderr)
        print("Label contexts:", json.dumps(contexts, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        raise SystemExit(2)
    print("Diff:", json.dumps(diff, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
