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
import random
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




class LowEndTalkTask(MonitorTask):
    """Low-request-volume incremental LET giveaway watcher."""

    name = "lowendtalk"

    def __init__(self, state_dir: Path, runtime_dir: Path, interval_seconds: int):
        self.state_path = state_dir / "lowendtalk.json"
        self.runtime_dir = runtime_dir / self.name
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.interval_seconds = interval_seconds
        self.failures = 0

    def next_interval_seconds(self) -> int:
        # 10-13 minutes by default; double after each failure (maximum 2 hours).
        return min(7200, self.interval_seconds * 2 ** min(self.failures, 4)) + random.randint(0, 180)

    def run_once(self) -> RunResult:
        current = self.runtime_dir / "current.json"
        events_file = self.runtime_dir / "events.json"
        # Stale files must not cause a false positive after a failed subprocess.
        current.unlink(missing_ok=True)
        events_file.unlink(missing_ok=True)
        rc = run_command([
            sys.executable, "scripts/lowendtalk_monitor.py",
            "--previous", str(self.state_path),
            "--output", str(current),
            "--events", str(events_file),
        ])
        snapshot = load_json(current)
        result = load_json(events_file)
        valid = (rc == 0 and isinstance(snapshot.get("last_comment_id"), int)
                 and isinstance(snapshot.get("last_page"), int)
                 and isinstance(result.get("events"), list)
                 and isinstance(result.get("initialized"), bool))
        if not valid:
            self.failures += 1
            print(f"[lowendtalk] probe invalid (rc={rc}); preserving checkpoint; "
                  f"consecutive failures={self.failures}", file=sys.stderr)
            return RunResult(False, {"rc": rc, "failures": self.failures})

        items = result["events"]
        notified = False
        if items:
            lines = [f"🚨 LowEndTalk: dustinc 新增 {len(items)} 条回复",
                     "RackNerd × AdminBolt 免费 VPS 活动", ""]
            for item in items[:8]:
                excerpt = " ".join(str(item.get("text") or "").split())[:600]
                lines.extend([f"📝 {excerpt or '(仅图片/无文本)'}",
                              f"🔗 {item['url']}", ""])
            if len(items) > 8:
                lines.append(f"还有 {len(items) - 8} 条，请打开活动帖查看。")
            lines.append("活动：https://lowendtalk.com/discussion/221872")
            notified = send_feishu("\n".join(lines))
            if not notified:
                self.failures += 1
                return RunResult(False, {"events": len(items), "notification_failed": True,
                                         "failures": self.failures})

        copy_atomic(current, self.state_path)
        self.failures = 0
        return RunResult(True, {"changed": bool(items), "events": len(items),
                                "initialized": result["initialized"], "notified": notified,
                                "last_page": snapshot["last_page"]})


@dataclass
class TaskStats:
    iterations: int = 0
    valid: int = 0
    failed: int = 0
    notifications: int = 0
    last_details: dict[str, Any] = field(default_factory=dict)


def build_tasks(args: argparse.Namespace) -> list[MonitorTask]:
    return [
        LowEndTalkTask(args.state_dir, args.runtime_dir, args.let_interval),
        HaxTask(
            args.state_dir,
            args.runtime_dir,
            args.hax_interval,
            args.hax_cleanup_interval,
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
    let_interval: int,
) -> None:
    lines = [
        "## VPS monitor hub",
        "",
        "- Scheduler: `one long-lived Actions job`",
        f"- Target runtime: `{duration_seconds}s`",
        f"- Hax interval: `{hax_interval}s`",
        f"- LowEndTalk interval: `{let_interval}s` + 0-180s jitter (failure backoff)",
        f"- Hax cleanup-window interval: `{hax_cleanup_interval}s` (16:55-17:20 UTC)",
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
    parser = argparse.ArgumentParser(description="Run long-lived VPS availability monitors")
    parser.add_argument("--duration", type=int, default=20_400)
    parser.add_argument("--hax-interval", type=int, default=300)
    parser.add_argument("--hax-cleanup-interval", type=int, default=60)
    parser.add_argument("--let-interval", type=int, default=600)
    parser.add_argument("--state-dir", type=Path, default=Path(".monitor-state"))
    parser.add_argument("--runtime-dir", type=Path, default=Path(".monitor-runtime"))
    parser.add_argument("--summary", type=Path, default=Path("monitor-summary.md"))
    args = parser.parse_args()

    for value, label in [
        (args.duration, "duration"),
        (args.hax_interval, "hax interval"),
        (args.hax_cleanup_interval, "hax cleanup interval"),
        (args.let_interval, "LET interval"),
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
        let_interval=args.let_interval,
    )
    write_github_output(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
