"""Dispatch trustworthy Hax inventory changes to the private renew repository.

The public monitor never loads Hax account credentials. A fine-grained GitHub
token scoped to the private target repository is required and stays in Actions
secrets; only inventory data travels in the repository_dispatch payload.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Mapping

DATACENTER = re.compile(r"^(?:EU-\d+|US-OpenVZ-\d+)$", re.I)
DESTINATION = "ParsifalC/moyu-renew"

# Only these three free Hax locations may initiate an automatic create.
# Names in the public Hax statistics use US-OpenVZ-n, whereas users often
# abbreviate them as US-n.
TARGET_DATACENTERS = ("US-OpenVZ-3", "EU-1", "US-OpenVZ-2")
TARGET_ORDER = {name.casefold(): index for index, name in enumerate(TARGET_DATACENTERS)}


def canonical_datacenter(value: object) -> str:
    raw = str(value or "").strip().casefold().replace("_", "-")
    aliases = {
        "us3": "US-OpenVZ-3", "us-3": "US-OpenVZ-3",
        "us2": "US-OpenVZ-2", "us-2": "US-OpenVZ-2",
        "eu1": "EU-1",
    }
    canonical = aliases.get(raw)
    if canonical is not None:
        return canonical
    return next((dc for dc in TARGET_DATACENTERS if dc.casefold() == raw), "")


def prioritize_datacenters(values: list[str]) -> list[str]:
    """Keep only target datacenters, in US-3 > EU-1 > US-2 order."""
    included = {canonical_datacenter(item) for item in values}
    return [dc for dc in TARGET_DATACENTERS if dc in included]


def dispatch_enabled(env: Mapping[str, str] | None = None) -> bool:
    data = os.environ if env is None else env
    return str(data.get("HAX_CREATE_DISPATCH_ENABLED", "false")).lower() in {"1", "true", "yes"}


def build_create_event(current: Mapping[str, Any], diff: Mapping[str, Any]) -> dict[str, Any] | None:
    """Require a real transition; permanent form options never constitute stock."""
    if diff.get("initialized") or not diff.get("changed") or current.get("errors"):
        return None
    visible = {canonical_datacenter(item) for item in current.get("datacenters") or []}
    added = [canonical_datacenter(dc)
             for dc in (diff.get("datacenters") or {}).get("added", [])
             if canonical_datacenter(dc) in visible]
    # The public create form may hide choices until the user logs in, whereas
    # /data-center can still reveal a real population decrease. Dispatch this
    # as a *candidate*; the private authenticated form must confirm the choice.
    releases = []
    for item in diff.get("release_candidates") or []:
        if not isinstance(item, dict):
            continue
        name = canonical_datacenter(item.get("datacenter"))
        source = str(item.get("source") or "")
        is_fresh_population = (
            source == "data-center" and current.get("data_center_stats_fresh") is True
        )
        is_visible_server_hint = source == "server-fallback" and name in visible
        released = item.get("released")
        if (name and type(released) is int and released > 0
                and (is_fresh_population or is_visible_server_hint)):
            releases.append({"datacenter": name, "released": released, "source": source})
    names = prioritize_datacenters(added + [r["datacenter"] for r in releases])
    if not names:
        return None
    checked_at = str(current.get("checked_at") or "")
    try:
        dt = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return None
    except ValueError:
        return None
    body = {"source": "ParsifalC/Resources", "checked_at": checked_at,
            "datacenters": names, "new_options": prioritize_datacenters(added),
            "release_candidates": [
                {"datacenter": r["datacenter"], "released": r["released"],
                 "source": r["source"]}
                for r in releases
            ]}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    body["event_id"] = digest
    return body


def dispatch_create_event(payload: Mapping[str, Any], env: Mapping[str, str] | None = None) -> str:
    """Return sent/disabled/not_configured/error; never leak token into logs."""
    data = os.environ if env is None else env
    if not dispatch_enabled(data):
        return "disabled"
    token = str(data.get("HAX_CREATE_DISPATCH_TOKEN") or "").strip()
    if not token:
        return "not_configured"
    req = urllib.request.Request(
        f"https://api.github.com/repos/{DESTINATION}/dispatches",
        data=json.dumps({"event_type": "hax_create_candidate", "client_payload": dict(payload)}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
            "User-Agent": "moyu-resources-hax-monitor",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return "sent" if response.status == 204 else "error"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Exception text may include request metadata; log only a safe category.
        print(f"[hax] private dispatch failed: {type(exc).__name__}")
        return "error"
