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


def dispatch_enabled(env: Mapping[str, str] | None = None) -> bool:
    data = os.environ if env is None else env
    return str(data.get("HAX_CREATE_DISPATCH_ENABLED", "false")).lower() in {"1", "true", "yes"}


def build_create_event(current: Mapping[str, Any], diff: Mapping[str, Any]) -> dict[str, Any] | None:
    """Require a real transition; permanent form options never constitute stock."""
    if diff.get("initialized") or not diff.get("changed") or current.get("errors"):
        return None
    visible = set(current.get("datacenters") or [])
    added = [dc for dc in (diff.get("datacenters") or {}).get("added", [])
             if isinstance(dc, str) and DATACENTER.fullmatch(dc) and dc in visible]
    releases = [r for r in diff.get("release_candidates") or []
                if isinstance(r, dict)
                and isinstance(r.get("datacenter"), str)
                and DATACENTER.fullmatch(r["datacenter"])
                and r["datacenter"] in visible
                and isinstance(r.get("released"), int) and r["released"] > 0]
    names = sorted(set(added) | {r["datacenter"] for r in releases})
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
            "datacenters": names, "new_options": sorted(added),
            "release_candidates": [
                {"datacenter": r["datacenter"], "released": r["released"],
                 "source": str(r.get("source") or "")[:40]}
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
