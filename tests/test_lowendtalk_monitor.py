"""Offline fixtures: parser, cursor initialization, page transitions and safe failures."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lowendtalk_monitor import check, parse_thread


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
    def test_parse_author_text_ids_and_pagination(self):
        p = parse_thread(html(1, [(10, "dustinc", "Batch 2!"), (11, "user", "Hi")], [2, 3]), page=1)
        self.assertEqual(p.pages, {1, 2, 3})
        self.assertEqual(p.comments[0], {"id": 10, "author": "dustinc", "text": "Batch 2!"})
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

    def test_too_many_unscanned_pages_preserves_cursor(self):
        previous = {"last_page": 2, "last_comment_id": 100}
        current = parse_thread(html(2, [(100, "other", "Hi")], [8]), page=2)
        with self.assertRaisesRegex(ValueError, "Too many unscanned"):
            check(previous, lambda n: current)

    def test_only_quote_mention_does_not_fake_author(self):
        p = parse_thread(html(1, [(20, "other", '<a href="/profile/dustinc">@dustinc</a>')]), page=1)
        self.assertEqual(p.comments[0]["author"], "other")


if __name__ == "__main__":
    unittest.main()
