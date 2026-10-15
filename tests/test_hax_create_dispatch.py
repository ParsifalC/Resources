"""Offline tests for the public Hax monitor -> private create signal boundary."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.hax_create_dispatch import build_create_event, dispatch_create_event


class CreateDispatchTests(unittest.TestCase):
    def setUp(self):
        self.current = {
            "checked_at": "2026-10-16T00:00:00+00:00",
            "datacenters": ["EU-1", "US-OpenVZ-2"],
            "errors": [],
        }
        self.diff = {
            "initialized": False, "changed": True,
            "datacenters": {"added": []},
            "release_candidates": [{"datacenter": "EU-1", "released": 2,
                                    "source": "data-center"}],
        }

    def test_real_release_signals_and_stable_event_id(self):
        one = build_create_event(self.current, self.diff)
        two = build_create_event(self.current, self.diff)
        self.assertEqual(one, two)
        self.assertEqual(one["datacenters"], ["EU-1"])
        self.assertEqual(one["release_candidates"][0]["released"], 2)
        self.assertEqual(len(one["event_id"]), 64)

    def test_new_option_only_triggers_if_currently_visible(self):
        self.diff["release_candidates"] = []
        self.diff["datacenters"] = {"added": ["EU-1", "FAKE-1"]}
        self.assertEqual(build_create_event(self.current, self.diff)["datacenters"], ["EU-1"])

    def test_no_trigger_for_baseline_or_persistent_option(self):
        self.assertIsNone(build_create_event(self.current, {**self.diff, "initialized": True}))
        self.assertIsNone(build_create_event(self.current, {**self.diff, "changed": False}))
        self.assertIsNone(build_create_event(self.current, {
            **self.diff, "datacenters": {"added": []}, "release_candidates": []}))
        self.assertIsNone(build_create_event({**self.current, "errors": ["timeout"]}, self.diff))

    def test_missing_token_never_calls_github(self):
        with patch("urllib.request.urlopen") as send:
            self.assertEqual(dispatch_create_event(
                {"event_id": "x"}, {"HAX_CREATE_DISPATCH_ENABLED": "true"}), "not_configured")
            send.assert_not_called()

    def test_disabled_by_default(self):
        with patch("urllib.request.urlopen") as send:
            self.assertEqual(dispatch_create_event({"event_id": "x"}, {}), "disabled")
            send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
