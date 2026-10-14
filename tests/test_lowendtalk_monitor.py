"""Offline fixtures: parser, cursor initialization, page transitions and safe failures."""
import sys
import os
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lowendtalk_monitor import check, parse_thread, classify_reply
from monitor_hub import format_lowendtalk_notification, LowEndTalkTask, build_tasks


def html(page, comments, pages=()):
    links = "".join(
        f'<a href="/discussion/221872/giveaway-example/p{p}">{p}</a>' for p in pages
    )
    rows = "".join(
        '<li class="Item Comment" id="Comment_%s">'
        '<div class="Meta"><a href="/profile/%s" class="Username">%s</a></div>'
        '<div class="Message userContent">%s</div></li>' % (cid, author, author, text)
        for cid, author, text in comments
    )
    return '<html><body><div class="Pager">' + links + '</div><ul>' + rows + '</ul></body></html>'


class LowEndTalkMonitorTests(unittest.TestCase):
    def test_pause_lowendtalk_without_stopping_hax(self):
        with TemporaryDirectory() as tmp:
            args = Namespace(
                state_dir=Path(tmp) / "state",
                runtime_dir=Path(tmp) / "runtime",
                let_interval=180,
                hax_interval=300,
                hax_cleanup_interval=60,
            )
            with patch.dict(os.environ, {"LET_MONITOR_ENABLED": "false"}):
                self.assertEqual([task.name for task in build_tasks(args)], ["hax"])
            with patch.dict(os.environ, {"LET_MONITOR_ENABLED": "true"}):
                self.assertEqual([task.name for task in build_tasks(args)], ["lowendtalk", "hax"])


    def test_three_minute_polling_with_jitter_and_failure_backoff(self):
        with TemporaryDirectory() as tmp:
            task = LowEndTalkTask(Path(tmp) / "state", Path(tmp) / "runtime", 180)
            with patch("monitor_hub.random.randint", return_value=0):
                self.assertEqual(task.next_interval_seconds(), 180)
                task.failures = 1
                self.assertEqual(task.next_interval_seconds(), 360)
            task.failures = 0
            with patch("monitor_hub.random.randint", return_value=30):
                self.assertEqual(task.next_interval_seconds(), 210)


    def test_parse_author_text_ids_and_pagination(self):
        p = parse_thread(html(1, [(10, "dustinc", "Batch 2!"), (11, "user", "Hi")], [2, 3]), page=1)
        self.assertEqual(p.pages, {1, 2, 3})
        self.assertEqual(p.comments[0], {"id": 10, "author": "dustinc", "text": "Batch 2!", "own_text": "Batch 2!"})
        self.assertEqual(p.comments[1]["author"], "user")

    def test_initialize_then_increment_only_dustinc(self):
        pages = {
            1: parse_thread(html(1, [(100, "other", "Hi")], [2]), page=1),
            2: parse_thread(html(2, [(101, "dustinc", "Old update")], [2]), page=2),
        }
        fetch = lambda n: pages[n]
        baseline, events = check({}, fetch)
        self.assertTrue(events["initialized"])
        self.assertEqual(events["events"], [])
        self.assertEqual(baseline["last_page"], 2)
        pages[2] = parse_thread(html(2, [
            (101, "dustinc", "Old update"),
            (102, "other", "New reply"),
            (103, "dustinc", "New batch"),
        ], [2]), page=2)
        updated, events = check(baseline, fetch)
        self.assertEqual([item["id"] for item in events["events"]], [103])
        self.assertEqual(updated["last_comment_id"], 103)
        _, repeat = check(updated, fetch)
        self.assertFalse(repeat["events"])

    def test_page_advance_scans_new_page_and_old_tail(self):
        previous = {"last_page": 2, "last_comment_id": 103}
        pages = {
            2: parse_thread(html(2, [(103, "other", "hi"), (105, "dustinc", "update")], [2, 3]), page=2),
            3: parse_thread(html(3, [(110, "other", "hi"), (111, "dustinc", "batch!")], [2, 3]), page=3),
        }
        snapshot, events = check(previous, lambda n: pages[n])
        self.assertEqual(snapshot["last_page"], 3)
        self.assertEqual([x["id"] for x in events["events"]], [105, 111])

    def test_challenge_is_never_accepted_as_page(self):
        with self.assertRaisesRegex(ValueError, "No identifiable comments"):
            parse_thread("<html>Just a moment... verify browser</html>", page=1)

    def test_busy_page_without_pagination_fails_closed(self):
        rows = [(i, "user", "hi") for i in range(101, 131)]
        with self.assertRaisesRegex(ValueError, "Pagination unavailable"):
            parse_thread(html(1, rows), page=1)

    def test_large_backlog_catches_up_in_bounded_batches(self):
        previous = {"last_page": 2, "last_comment_id": 100}
        pages = {
            2: parse_thread(html(2, [(100, "other", "Hi")], [8]), page=2),
            **{n: parse_thread(html(n, [(100 + n, "dustinc", f"Update {n}")], [8]), page=n)
               for n in range(3, 9)},
        }
        visited = []

        def fetch(page):
            visited.append(page)
            return pages[page]

        first, first_events = check(previous, fetch)
        self.assertEqual(visited, [2, 3, 4, 5, 6, 7])
        self.assertEqual(first["last_page"], 7)
        self.assertEqual(first["last_comment_id"], 107)
        self.assertEqual([e["id"] for e in first_events["events"]], [103, 104, 105, 106, 107])

        visited.clear()
        second, second_events = check(first, fetch)
        self.assertEqual(visited, [7, 8])
        self.assertEqual(second["last_page"], 8)
        self.assertEqual(second["last_comment_id"], 108)
        self.assertEqual([e["id"] for e in second_events["events"]], [108])

        _, third_events = check(second, fetch)
        self.assertEqual(third_events["events"], [])

    def test_catchup_failure_never_changes_previous_checkpoint(self):
        previous = {"last_page": 2, "last_comment_id": 100}
        current = parse_thread(html(2, [(100, "other", "Hi")], [8]), page=2)

        def fetch(page):
            if page == 4:
                raise RuntimeError("HTTP 429")
            return current

        with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
            check(previous, fetch)
        self.assertEqual(previous, {"last_page": 2, "last_comment_id": 100})

    def test_three_consecutive_failures_send_single_health_alert(self):
        with TemporaryDirectory() as tmp:
            task = LowEndTalkTask(Path(tmp) / "state", Path(tmp) / "runtime", 180)
            with patch("monitor_hub.run_command", return_value=1), \
                 patch("monitor_hub.send_feishu", return_value=True) as notify:
                for _ in range(5):
                    result = task.run_once()
                    self.assertFalse(result.valid)
                self.assertEqual(task.failures, 5)
                self.assertEqual(notify.call_count, 1)
                self.assertIn("连续 3 次", notify.call_args.args[0])

    def test_only_quote_mention_does_not_fake_author(self):
        p = parse_thread(html(1, [(20, "other", '<a href="/profile/dustinc">@dustinc</a>')]), page=1)
        self.assertEqual(p.comments[0]["author"], "other")


    def test_classify_real_announcement_extract_keyword_verbatim(self):
        body = ("RackNerd & AdminBolt Giveaway! The next 10 comments with "
                "the following hash tag will receive a FREE 4 GB RAM VPS "
                "in Los Angeles for 1 year. KEYWORD; #ADMINBOLT = A MODERN "
                "PANEL WITHOUT THE PER-ACCOUNT TAX! Note: Winners will be DM’d")
        self.assertEqual(classify_reply(body),
                         ("giveaway", "#ADMINBOLT = A MODERN PANEL WITHOUT THE PER-ACCOUNT TAX!"))

    def test_preheat_and_winner_followup_distinct_from_regular(self):
        self.assertEqual(classify_reply("We need to drum up some demand! What do you think?")[0], "warmup")
        self.assertEqual(classify_reply("Who's ready for another giveaway?!")[0], "warmup")
        self.assertEqual(classify_reply("Let's do this then!")[0], "warmup")
        self.assertEqual(classify_reply("Latest giveaway winners have been DM'd :)")[0], "winners")
        self.assertEqual(classify_reply("Hi folks, thank you for the feedback!")[0], "other")
        self.assertEqual(classify_reply("We have plenty more giveaways ahead")[0], "other")

    def test_quoted_giveaway_does_not_trigger_false_alarm(self):
        body = ('<blockquote class="Quote">RackNerd &amp; AdminBolt Giveaway! '
                'The next 10 comments will receive a FREE VPS. KEYWORD; #OLD</blockquote>'
                '<p>Thanks for taking part, great to have you here!</p>')
        p = parse_thread(html(1, [(100, "dustinc", body)]), page=1)
        self.assertIn("KEYWORD", p.comments[0]["text"])
        self.assertEqual(p.comments[0]["own_text"], "Thanks for taking part, great to have you here!")
        self.assertEqual(classify_reply(p.comments[0]["own_text"]), ("other", None))

    def test_capture_utc_created_at_from_real_style_comment_header(self):
        markup = ('<li class="Item Comment" id="Comment_4879585">'
                  '<div class="Item-Header CommentHeader"><a href="/profile/dustinc">'
                  'dustinc</a><time datetime="2026-10-09T19:45:40+00:00">'
                  'October 9</time></div><div class="Message userContent">'
                  'Lets do this then!</div></li>')
        parsed = parse_thread(markup, page=1)
        self.assertEqual(parsed.comments[0]["created_at"], "2026-10-09T19:45:40+00:00")
        self.assertEqual(parsed.comments[0]["own_text"], "Lets do this then!")

    def test_sync_all_new_replies_and_keep_bounded_history(self):
        previous = {
            "last_page": 1, "last_comment_id": 120,
            "recent_dustinc_comments": [
                {"id": i, "text": "old"} for i in range(1, 121)
            ],
        }
        new_page = parse_thread(html(1, [
            (119, "user", "ok"),
            (121, "dustinc", "Thanks, happy to help"),
            (122, "user", "Hello"),
            (123, "dustinc", "Latest giveaway winners have been DM'd"),
        ]), page=1)
        state, events = check(previous, lambda n: new_page)
        self.assertEqual([e["id"] for e in events["events"]], [121, 123])
        self.assertEqual([e["category"] for e in events["events"]], ["other", "winners"])
        self.assertEqual(len(state["recent_dustinc_comments"]), 120)
        self.assertEqual(state["recent_dustinc_comments"][-1]["id"], 123)
        state_again, events_again = check(state, lambda n: new_page)
        self.assertEqual(events_again["events"], [])
        self.assertEqual(state_again["recent_dustinc_comments"], state["recent_dustinc_comments"])

    def test_feishu_message_lists_every_reply_and_keyword(self):
        rows = [
            {"id": 1, "created_at": "2026-10-09T19:45:40+00:00",
             "category": "giveaway", "keyword": "#ADMINBOLT = TEST!",
             "text": "The next 10 comments win FREE VPS", "url": "https://lowendtalk.com/comment/1"},
            {"id": 2, "created_at": None, "category": "warmup", "keyword": None,
             "text": "Another giveaway!", "url": "https://lowendtalk.com/comment/2"},
            {"id": 3, "created_at": None, "category": "other", "keyword": None,
             "text": "Thanks!", "url": "https://lowendtalk.com/comment/3"},
        ]
        body = format_lowendtalk_notification(rows)
        self.assertIn("新批次发布", body)
        self.assertIn("#ADMINBOLT = TEST!", body)
        self.assertIn("2026-10-10 03:45:40 (UTC+8)", body)
        self.assertIn("发放 1 / 预热 1 / 结果 0 / 普通 1", body)
        for row in rows:
            self.assertIn(row["url"], body)



if __name__ == "__main__":
    unittest.main()
