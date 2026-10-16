"""Offline tests for the public Hax monitor -> private create signal boundary."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts.hax_monitor import make_diff, parse_datacenters

from scripts.hax_create_dispatch import build_create_event, dispatch_create_event


class CreateDispatchTests(unittest.TestCase):
    def setUp(self):
        self.current = {
            "checked_at": "2026-10-16T00:00:00+00:00",
            "datacenters": ["EU-1", "US-OpenVZ-2", "US-OpenVZ-3"],
            "data_center_stats_fresh": True,
            "datacenter_source": "dom_select",
            "servers_fresh": True,
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
        self.assertIsNotNone(build_create_event({**self.current, "errors": ["create-vps: options missing"]}, self.diff))
        self.assertIsNone(build_create_event({**self.current, "data_center_stats_fresh": False}, self.diff))

    def test_priority_is_us3_then_eu1_then_us2(self):
        self.diff["datacenters"] = {"added": ["EU-1", "US-2", "US-3"]}
        event = build_create_event(self.current, self.diff)
        self.assertEqual(
            event["datacenters"], ["US-OpenVZ-3", "EU-1", "US-OpenVZ-2"]
        )

    def test_only_one_available_candidate_is_selected(self):
        self.diff["datacenters"] = {"added": []}
        self.diff["release_candidates"] = [
            {"datacenter": "US-2", "released": 1, "source": "data-center"}
        ]
        self.assertEqual(
            build_create_event(self.current, self.diff)["datacenters"],
            ["US-OpenVZ-2"],
        )

    def test_out_of_scope_datacenters_do_not_trigger(self):
        self.diff["datacenters"] = {"added": ["EU-2"]}
        self.diff["release_candidates"] = [
            {"datacenter": "EU-2", "released": 1, "source": "data-center"}
        ]
        self.assertIsNone(build_create_event(self.current, self.diff))

    def test_fresh_release_signal_without_public_form_options(self):
        self.current["datacenters"] = []
        self.assertEqual(
            build_create_event(self.current, self.diff)["datacenters"], ["EU-1"]
        )

    def test_no_raw_html_inference_of_stock(self):
        html = '<script>let fake = "US-OpenVZ-3";</script><p>EU-1 is online</p>'
        names, source = parse_datacenters(html)
        self.assertEqual((names, source), ([], "unavailable"))

    def test_only_real_datacenter_select_options(self):
        html = '<select id="datacenter"><option>Select</option><option>US-OpenVZ-3</option><option>EU-2</option><option>Server Status</option></select>'
        names, source = parse_datacenters(html)
        self.assertEqual(source, "dom_select")
        self.assertEqual(names, ["EU-2", "US-OpenVZ-3"])

    def test_statistic_decrease_with_missing_public_options(self):
        now = datetime.now(timezone.utc)
        before = {
            "checked_at": (now - timedelta(minutes=5)).isoformat(),
            "datacenters": [], "datacenter_source": "unavailable",
            "servers": {}, "servers_fresh": False,
            "data_center_stats_fresh": True,
            "data_center_stats": {"servers": {"EU-1": 202, "US-OpenVZ-3": 311}},
        }
        after = {
            "checked_at": now.isoformat(), "datacenters": [],
            "datacenter_source": "unavailable", "servers": {},
            "servers_fresh": False, "data_center_stats_fresh": True,
            "data_center_stats": {"servers": {"EU-1": 202, "US-OpenVZ-3": 310}},
            "errors": ["create-vps: no actionable options"],
        }
        diff = make_diff(before, after)
        self.assertEqual(diff["release_candidates"][0]["datacenter"], "US-OpenVZ-3")
        self.assertEqual(build_create_event(after, diff)["datacenters"], ["US-OpenVZ-3"])

    def test_stale_previous_statistics_do_not_trigger_create(self):
        now = datetime.now(timezone.utc)
        before = {
            "checked_at": (now - timedelta(hours=2)).isoformat(),
            "datacenters": [], "datacenter_source": "unavailable",
            "servers": {}, "servers_fresh": False,
            "data_center_stats_fresh": True,
            "data_center_stats": {"servers": {"EU-1": 202}},
        }
        after = dict(before, checked_at=now.isoformat(),
                     data_center_stats={"servers": {"EU-1": 201}})
        diff = make_diff(before, after)
        self.assertEqual(diff["release_candidates"], [])
        self.assertIsNone(build_create_event(after, diff))

    def test_previous_inherited_nonfresh_stats_never_trigger(self):
        now = datetime.now(timezone.utc)
        before = {
            "checked_at": (now - timedelta(minutes=5)).isoformat(),
            "datacenters": [], "datacenter_source": "unavailable",
            "servers": {}, "servers_fresh": False,
            "data_center_stats_fresh": False,
            "data_center_stats": {"servers": {"EU-1": 202}},
        }
        after = dict(before, checked_at=now.isoformat(),
                     data_center_stats_fresh=True,
                     data_center_stats={"servers": {"EU-1": 201}})
        diff = make_diff(before, after)
        self.assertEqual(diff["release_candidates"], [])

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
