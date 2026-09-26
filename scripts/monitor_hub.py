#!/usr/bin/env python3
"""Long-lived scheduler for VPS availability monitors.

The GitHub Actions job owns one runner for several hours. This process keeps
provider-specific checks isolated, schedules each provider independently, and
persists only valid snapshots in --state-dir. Adding another monitor should
normally mean adding one MonitorTask implementation and registering it in
build_tasks(), not adding another scheduled workflow.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        value = json.loads(raw) if raw else {}
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def copy_atomic(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    shutil.copyfile(source, tmp)
    tmp.replace(target)


def run_command(args: list[str], *, env: dict[str, str] | None = None) -> int:
    printable = " ".join(args)
    print(f"$ {printable}", flush=True)
    completed = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        check=False,
        text=True,
    )
    return completed.returncode


def send_feishu(text: str) -> bool:
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    chat_id = os.environ.get("FEISHU_CHAT_ID", "").strip()
    if not (app_id and app_secret and chat_id):
        print("Feishu secrets are not fully configured; notification skipped.", file=sys.stderr)
        return False

    def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        code = data.get("code", data.get("StatusCode", 0))
        if code not in (0, "0", None):
            raise RuntimeError(
                f"Feishu API error: code={code}, msg={data.get('msg', data.get('StatusMessage'))}"
            )
        return data

    try:
        token_data = post_json(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            {"app_id": app_id, "app_secret": app_secret},
        )
        token = str(token_data.get("tenant_access_token") or "").strip()
        if not token:
            raise RuntimeError("Feishu response missing tenant_access_token")
        query = urllib.parse.urlencode({"receive_id_type": "chat_id"})
        post_json(
            f"https://open.feishu.cn/open-apis/im/v1/messages?{query}",
            {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception as exc:
        print(f"Feishu notification failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return False

    print("Feishu notification sent successfully.")
    return True


def display_time(checked_at: str | None) -> str:
    if not checked_at:
        return "unknown"
    try:
        dt = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S (UTC+8)")
    except ValueError:
        return checked_at


@dataclass
class RunResult:
    valid: bool
    details: dict[str, Any] = field(default_factory=dict)


class MonitorTask:
    name: str
    interval_seconds: int

    def run_once(self) -> RunResult:
        raise NotImplementedError

    def next_interval_seconds(self) -> int:
        return self.interval_seconds


class HaxTask(MonitorTask):
    name = "hax"

    def __init__(self, state_dir: Path, runtime_dir: Path, interval_seconds: int, cleanup_interval_seconds: int):
        self.state_path = state_dir / "hax.json"
        self.runtime_dir = runtime_dir / self.name
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = interval_seconds
        self.cleanup_interval_seconds = cleanup_interval_seconds

    def next_interval_seconds(self) -> int:
        now = datetime.now(timezone.utc)
        minutes = now.hour * 60 + now.minute
        if 16 * 60 + 55 <= minutes <= 17 * 60 + 20:
            return self.cleanup_interval_seconds
        return self.interval_seconds

    def run_once(self) -> RunResult:
        current = self.runtime_dir / "current.json"
        diff_path = self.runtime_dir / "diff.json"
        rc = run_command(
            [
                sys.executable,
                "scripts/hax_monitor.py",
                "--previous",
                str(self.state_path),
                "--output",
                str(current),
                "--diff-output",
                str(diff_path),
            ]
        )
        snapshot = load_json(current)
        diff = load_json(diff_path)
        errors = snapshot.get("errors") or []
        valid = rc == 0 and not errors and bool(snapshot)
        notified = False

        if not valid:
            print(f"[hax] invalid probe; preserving previous snapshot. rc={rc} errors={errors}", file=sys.stderr)
            return RunResult(False, {"rc": rc, "errors": errors})

        if diff.get("changed") and not diff.get("initialized"):
            notified = send_feishu(self._notification(snapshot, diff))
        copy_atomic(current, self.state_path)
        return RunResult(True, {"changed": bool(diff.get("changed")), "notified": notified})

    @staticmethod
    def _notification(current: dict[str, Any], diff: dict[str, Any]) -> str:
        added = (diff.get("datacenters") or {}).get("added", [])
        removed = (diff.get("datacenters") or {}).get("removed", [])
        releases = diff.get("release_candidates") or []

        if releases:
            lines = ["⚡ Hax 疑似释放可用席位", "━━━━━━━━━━━━━━━━━━", ""]
            for item in releases:
                lines.append(
                    f"🟠 {item.get('datacenter')}: {item.get('before')} → {item.get('after')}，"
                    f"减少 {item.get('released')} 台"
                )
                lines.append(f"   信号源: {item.get('source')}；建议立即手动尝试创建")
        elif added:
            lines = ["🚨 Hax 出现新的 Create VPS 选项", "━━━━━━━━━━━━━━━━━━", ""]
            lines.extend(f"🟢 {name} 新出现" for name in added)
            lines.extend(["", "⚠️ 这仍不是成功库存确认，只是比长期常驻选项更强的信号。"])
        else:
            lines = ["📊 Hax 可用性状态变化", "━━━━━━━━━━━━━━━━━━", ""]

        if removed:
            if releases or added:
                lines.append("")
            lines.extend(f"🔴 Create VPS 选项 {name} 已消失" for name in removed)

        stats_diff = (diff.get("data_center_stats") or {}).get("servers") or {}
        if stats_diff:
            lines.extend(["", "📉 Data Center 在线 VPS 数变化"])
            for name, change in stats_diff.items():
                delta = change.get("delta")
                suffix = "" if delta is None else f" ({delta:+d})"
                lines.append(f"• {name}: {change.get('before')} → {change.get('after')}{suffix}")

        server_diff = diff.get("servers") or {}
        if server_diff:
            lines.extend(["", "📈 /server 页面统计变化（辅助）"])
            for name, change in server_diff.items():
                delta = change.get("delta")
                suffix = "" if delta is None else f" ({delta:+d})"
                lines.append(f"• {name}: {change.get('before')} → {change.get('after')}{suffix}")

        lines.extend(["", "🌐 当前 Create VPS 表单选项（不等于好鸡/真实库存）"])
        added_set = set(added)
        datacenters = current.get("datacenters") or []
        lines.extend(f"• {name}{' 🆕' if name in added_set else ''}" for name in datacenters)
        if not datacenters:
            lines.append("• (none)")

        stats = current.get("data_center_stats") or {}
        stats_servers = stats.get("servers") or {}
        if stats_servers:
            suffix = "" if current.get("data_center_stats_fresh") else "（沿用上一份有效值）"
            lines.extend(["", f"🧭 Data Center Server Statistics{suffix}"])
            lines.extend(f"• {name}: {count} VPS" for name, count in stats_servers.items())
            if stats.get("online_total") is not None:
                lines.append(f"• Online total: {stats.get('online_total')} VPS")

        lines.extend(
            [
                "",
                "ℹ️ 只有成功创建并实际 Online 才能确认是可用 VPS；当前监控保持只读，不会代你创建。",
                f"🕒 检测时间：{display_time(current.get('checked_at'))}",
                "",
                "🔐 登录 Hax：https://hax.co.id/login",
            ]
        )
        return "\n".join(lines)


class OpenWorldTask(MonitorTask):
    name = "openworld"

    def __init__(
        self,
        state_dir: Path,
        runtime_dir: Path,
        interval_seconds: int,
        *,
        save_html_once: bool,
    ):
        self.public_state = state_dir / "openworld.json"
        self.inventory_state = state_dir / "openworld-inventory.json"
        self.runtime_dir = runtime_dir / self.name
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = interval_seconds
        self.save_html_once = save_html_once

    def run_once(self) -> RunResult:
        public_valid, public_details = self._run_public()
        inventory_valid, inventory_details = self._run_inventory()
        return RunResult(
            public_valid and inventory_valid,
            {"public": public_details, "inventory": inventory_details},
        )

    def _run_public(self) -> tuple[bool, dict[str, Any]]:
        current = self.runtime_dir / "current.json"
        diff_path = self.runtime_dir / "diff.json"
        rc = run_command(
            [
                sys.executable,
                "scripts/openworld_monitor.py",
                "--previous",
                str(self.public_state),
                "--output",
                str(current),
                "--diff-output",
                str(diff_path),
            ]
        )
        snapshot = load_json(current)
        diff = load_json(diff_path)
        valid = rc == 0 and snapshot.get("status") == "OK" and not snapshot.get("errors")
        notified = False
        if not valid:
            print(f"[openworld/public] invalid probe; preserving snapshot. rc={rc}", file=sys.stderr)
            return False, {"rc": rc}

        if diff.get("changed") and not diff.get("initialized"):
            notified = send_feishu(self._public_notification(snapshot, diff))
        copy_atomic(current, self.public_state)
        return True, {"changed": bool(diff.get("changed")), "notified": notified}

    def _run_inventory(self) -> tuple[bool, dict[str, Any]]:
        auth_probe = self.runtime_dir / "auth_probe.json"
        command = [sys.executable, "scripts/openworld_auth_probe.py", str(auth_probe)]
        if self.save_html_once:
            command.extend(["--html-output", str(ROOT / "openworld-createvps.html")])
            self.save_html_once = False

        rc = run_command(command)
        current = load_json(auth_probe)
        previous = load_json(self.inventory_state)
        state = current.get("inventory_state", "UNKNOWN")
        valid = current.get("auth_state") == "AUTHENTICATED" and state in {"AVAILABLE", "OUT_OF_STOCK"}
        if not valid:
            notified = False
            if rc == 2:
                print("[openworld/inventory] session expired or no longer reaches authenticated /createvps.", file=sys.stderr)
                should_notify = (
                    previous.get("auth_state") != "UNAUTHENTICATED"
                    or not previous.get("auth_alerted")
                )
                if should_notify:
                    notified = send_feishu(self._session_expired_notification(current))
                previous["auth_state"] = "UNAUTHENTICATED"
                previous["auth_checked_at"] = current.get("checked_at")
                previous["auth_alerted"] = notified or bool(previous.get("auth_alerted"))
                write_json(self.inventory_state, previous)
            else:
                print(
                    f"[openworld/inventory] invalid probe; preserving snapshot. rc={rc} "
                    f"auth={current.get('auth_state')} inventory={state}",
                    file=sys.stderr,
                )
            return False, {
                "rc": rc,
                "auth": current.get("auth_state"),
                "state": state,
                "notified": notified,
            }

        inventory = current.get("inventory") or {}
        snapshot = {
            "status": state,
            "stock": inventory.get("free_stock_total"),
            "free_plans": inventory.get("free_plans") or [],
            "source": current.get("source"),
            "auth_state": "AUTHENTICATED",
            "auth_checked_at": current.get("checked_at"),
            "auth_alerted": False,
        }
        inventory_keys = ("status", "stock", "free_plans", "source")
        previous_core = {key: previous.get(key) for key in inventory_keys}
        snapshot_core = {key: snapshot.get(key) for key in inventory_keys}
        initialized = not bool(previous.get("status"))
        changed = not initialized and snapshot_core != previous_core
        restocked = not initialized and state == "AVAILABLE" and previous.get("status") == "OUT_OF_STOCK"
        notified = False
        if restocked:
            notified = send_feishu(self._inventory_notification(current))
        snapshot["checked_at"] = current.get("checked_at")
        write_json(self.inventory_state, snapshot)
        return True, {
            "changed": changed,
            "restocked": restocked,
            "notified": notified,
            "state": state,
            "stock": snapshot.get("stock"),
        }

    @staticmethod
    def _public_notification(current: dict[str, Any], diff: dict[str, Any]) -> str:
        labels = {"nodes": "Nodes", "vps": "VPS", "ips": "IPs"}
        lines = ["📡 OpenWorld 公开容量数量变化", "━━━━━━━━━━━━━━━━━━", ""]
        for key, change in (diff.get("counters") or {}).items():
            delta = change.get("delta")
            suffix = "" if delta is None else f" ({delta:+d})"
            lines.append(
                f"• {labels.get(key, key)}: {change.get('before')} → {change.get('after')}{suffix}"
            )
        lines.extend(
            [
                "",
                "⚠️ 这是公开数量变化；Free VPS 是否有货以登录态库存探针为准。",
                f"🕒 检测时间：{display_time(current.get('checked_at'))}",
                "🌐 https://openworld.eu.org/",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _session_expired_notification(current: dict[str, Any]) -> str:
        return "\n".join(
            [
                "⚠️ OpenWorld 登录 Cookie 已过期",
                "━━━━━━━━━━━━━━━━━━",
                "",
                "❌ /createvps 已无法维持登录态（auth=UNAUTHENTICATED）",
                f"🕒 检测时间：{display_time(current.get('checked_at'))}",
                "",
                "请重新登录 OpenWorld，复制新的 sessioncookie 值后执行：",
                "",
                "gh secret set OPENWORLD_SESSIONCOOKIE --repo ParsifalC/Resources --body '新的 sessioncookie 值'",
                "",
                "如果新的 sessioncookie 已在 macOS 剪贴板，也可以执行：",
                "pbpaste | gh secret set OPENWORLD_SESSIONCOOKIE --repo ParsifalC/Resources",
                "",
                "ℹ️ 只需要 sessioncookie 的值，不要带 sessioncookie= 前缀。",
            ]
        )

    @staticmethod
    def _inventory_notification(current: dict[str, Any]) -> str:
        inventory = current.get("inventory") or {}
        stock = inventory.get("free_stock_total")
        locations: list[str] = []
        for plan in inventory.get("free_plans") or []:
            for location in plan.get("locations") or []:
                if location.get("available"):
                    name = location.get("name") or location.get("code") or "unknown"
                    if name not in locations:
                        locations.append(name)
        return "\n".join(
            [
                "🚀 OpenWorld Free VPS 补货",
                "━━━━━━━━━━━━━━━━━━",
                "",
                "✅ 当前状态：AVAILABLE",
                f"📦 Free 库存：{stock if stock is not None else 'unknown'}",
                f"🌍 可用地点：{', '.join(locations) if locations else '未标明'}",
                "",
                "🔗 https://openworld.eu.org/createvps",
                "",
                "该结果来自登录态 /createvps 页面中的结构化 Free plan stock；监控仅 GET，不提交创建请求。",
            ]
        )


@dataclass
class TaskStats:
    iterations: int = 0
    valid: int = 0
    failed: int = 0
    notifications: int = 0
    last_details: dict[str, Any] = field(default_factory=dict)


def build_tasks(args: argparse.Namespace) -> list[MonitorTask]:
    return [
        HaxTask(
            args.state_dir,
            args.runtime_dir,
            args.hax_interval,
            args.hax_cleanup_interval,
        ),
        OpenWorldTask(
            args.state_dir,
            args.runtime_dir,
            args.openworld_interval,
            save_html_once=args.manual_artifact,
        ),
    ]


def run_scheduler(tasks: list[MonitorTask], duration_seconds: int) -> dict[str, TaskStats]:
    deadline = time.monotonic() + duration_seconds
    next_due = {task.name: time.monotonic() for task in tasks}
    stats = {task.name: TaskStats() for task in tasks}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
        while True:
            now = time.monotonic()
            if now >= deadline:
                break

            due = [task for task in tasks if next_due[task.name] <= now]
            if not due:
                sleep_for = min(next_due.values()) - now
                time.sleep(max(0.1, min(sleep_for, deadline - now)))
                continue

            futures = {}
            for task in due:
                stats[task.name].iterations += 1
                iteration = stats[task.name].iterations
                print(
                    f"=== {task.name} check #{iteration} at "
                    f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} ===",
                    flush=True,
                )
                futures[pool.submit(task.run_once)] = task

            for future, task in futures.items():
                try:
                    result = future.result()
                except Exception as exc:
                    print(f"[{task.name}] unhandled task error: {type(exc).__name__}: {exc}", file=sys.stderr)
                    result = RunResult(False, {"exception": f"{type(exc).__name__}: {exc}"})

                item = stats[task.name]
                if result.valid:
                    item.valid += 1
                else:
                    item.failed += 1
                item.last_details = result.details
                item.notifications += _count_notifications(result.details)

                interval = task.next_interval_seconds()
                if task.name == "hax" and interval != task.interval_seconds:
                    print(f"[hax] cleanup window: next check in {interval}s.")
                next_due[task.name] = time.monotonic() + interval

    return stats


def _count_notifications(value: Any) -> int:
    if isinstance(value, dict):
        count = 1 if value.get("notified") is True else 0
        return count + sum(_count_notifications(v) for k, v in value.items() if k != "notified")
    if isinstance(value, list):
        return sum(_count_notifications(v) for v in value)
    return 0


def write_summary(
    path: Path,
    stats: dict[str, TaskStats],
    *,
    duration_seconds: int,
    hax_interval: int,
    hax_cleanup_interval: int,
    openworld_interval: int,
) -> None:
    lines = [
        "## VPS monitor hub",
        "",
        "- Scheduler: `one long-lived Actions job`",
        f"- Target runtime: `{duration_seconds}s`",
        f"- Hax interval: `{hax_interval}s`",
        f"- Hax cleanup-window interval: `{hax_cleanup_interval}s` (16:55-17:20 UTC)",
        f"- OpenWorld interval: `{openworld_interval}s`",
        "- OpenWorld Create VPS POST/submission: `none`",
        "",
        "### Provider results",
    ]
    for name in sorted(stats):
        item = stats[name]
        lines.extend(
            [
                f"- **{name}**: iterations `{item.iterations}`, valid `{item.valid}`, "
                f"failed `{item.failed}`, notifications `{item.notifications}`",
                f"  - Last result: `{json.dumps(item.last_details, ensure_ascii=False, sort_keys=True)}`",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_github_output(stats: dict[str, TaskStats]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        for name, item in sorted(stats.items()):
            prefix = name.replace("-", "_")
            handle.write(f"{prefix}_iterations={item.iterations}\n")
            handle.write(f"{prefix}_valid={item.valid}\n")
            handle.write(f"{prefix}_failed={item.failed}\n")
            handle.write(f"{prefix}_notifications={item.notifications}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Hax/OpenWorld monitors inside one long-lived process")
    parser.add_argument("--duration", type=int, default=20_400)
    parser.add_argument("--hax-interval", type=int, default=300)
    parser.add_argument("--hax-cleanup-interval", type=int, default=60)
    parser.add_argument("--openworld-interval", type=int, default=900)
    parser.add_argument("--state-dir", type=Path, default=Path(".monitor-state"))
    parser.add_argument("--runtime-dir", type=Path, default=Path(".monitor-runtime"))
    parser.add_argument("--summary", type=Path, default=Path("monitor-summary.md"))
    parser.add_argument("--manual-artifact", action="store_true")
    args = parser.parse_args()

    for value, label in [
        (args.duration, "duration"),
        (args.hax_interval, "hax interval"),
        (args.hax_cleanup_interval, "hax cleanup interval"),
        (args.openworld_interval, "OpenWorld interval"),
    ]:
        if value <= 0:
            parser.error(f"{label} must be > 0")

    args.state_dir.mkdir(parents=True, exist_ok=True)
    args.runtime_dir.mkdir(parents=True, exist_ok=True)

    tasks = build_tasks(args)
    stats = run_scheduler(tasks, args.duration)
    write_summary(
        args.summary,
        stats,
        duration_seconds=args.duration,
        hax_interval=args.hax_interval,
        hax_cleanup_interval=args.hax_cleanup_interval,
        openworld_interval=args.openworld_interval,
    )
    write_github_output(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
